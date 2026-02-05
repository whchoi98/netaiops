# This is the host agent that is responsible for understanding the other
# agents in the ecosystem and then invoking the agent that is the most relevant to this
# use case using Strands and BedrockAgentCoreApp
import yaml
import asyncio
import json
import uuid
import time
import threading
from datetime import datetime, timedelta
from typing import Any, AsyncIterable, List, Dict, Optional
from pathlib import Path
from asyncio import Semaphore

import httpx
import nest_asyncio
from a2a.client import A2ACardResolver
# These are the A2A types for communication
from a2a.types import (
    AgentCard, 
    MessageSendParams, 
    SendMessageRequest, 
    SendMessageResponse, 
    SendMessageSuccessResponse, 
    Task,
)

# Strands and BedrockAgentCore imports
from strands import Agent
from strands.models import BedrockModel
from strands_tools import current_time
from strands.tools import tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient
import logging

# import the remote agent connection
try:
    # Try relative imports first (when run as module)
    from .remote_agent_connection import RemoteAgentConnections
    from .context import HostAgentContext
    from .memory_hook_provider import HostMemoryHook
    from .streaming_queue import HostStreamingQueue
    from .utils import get_ssm_parameter
    from .access_token import get_gateway_access_token
except ImportError:
    # Fall back to absolute imports (when run as script)
    from remote_agent_connection import RemoteAgentConnections
    from context import HostAgentContext
    from memory_hook_provider import HostMemoryHook
    from streaming_queue import HostStreamingQueue
    from utils import get_ssm_parameter
    from access_token import get_gateway_access_token

# Environment flags
import os
os.environ["STRANDS_OTEL_ENABLE_CONSOLE_EXPORT"] = "true"
os.environ["STRANDS_TOOL_CONSOLE_MODE"] = "enabled"

# 기본 모델 ID (환경변수로 오버라이드 가능)
DEFAULT_MODEL_ID = "global.anthropic.claude-opus-4-5-20251101-v1:0"

# Enhanced logging setup for troubleshooting
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Also set httpx logging to debug
httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.DEBUG)

nest_asyncio.apply()

def load_config() -> dict:
    """Load configuration from config.yaml file."""
    config_path = Path(__file__).parent / 'main_agent.yaml'
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        raise e
    
config = load_config()
print(f"Loaded the main agent config file: {json.dumps(config, indent=4)}")

# Bedrock app and global agent instance - configure to avoid uvicorn compatibility issues
app = BedrockAgentCoreApp()
memory_client = MemoryClient()

# Essential uvicorn compatibility fix
import asyncio

# Store the original asyncio.run function
_original_asyncio_run = asyncio.run

def patched_asyncio_run(coro, **kwargs):
    """Patched asyncio.run that removes unsupported loop_factory parameter"""
    # Remove loop_factory if it exists in kwargs
    filtered_kwargs = {k: v for k, v in kwargs.items() if k != 'loop_factory'}
    return _original_asyncio_run(coro, **filtered_kwargs)

# Apply the patch to asyncio.run globally
asyncio.run = patched_asyncio_run
print("✅ Applied asyncio.run compatibility fix")

class HostAgent:
    """
    This is the host agent that contains information about the remote agent
    connections, cards, agents using Strands and BedrockAgentCore.
    """
    def __init__(
        self,
        bearer_token: str,
        memory_hook: HostMemoryHook = None,
        bedrock_model_id: str = None,
        system_prompt: str = None,
    ):
        # 환경변수 > 파라미터 > 기본값 순으로 모델 ID 결정
        if bedrock_model_id is None:
            bedrock_model_id = os.environ.get('BEDROCK_MODEL_ID', DEFAULT_MODEL_ID)
        self.model_id = bedrock_model_id
        self.model = BedrockModel(
            model_id=self.model_id,
        )
        self.memory_hook = memory_hook
        self.bearer_token = bearer_token
        
        # Rate limiting: Allow max 2 concurrent Bedrock API calls
        self._bedrock_semaphore = Semaphore(2)
        # Track last API call time for exponential backoff
        self._last_api_call_time = 0
        self._min_delay_between_calls = 1.0  # Minimum 1 second between calls
        
        self.remote_agent_connections: dict[str, RemoteAgentConnections] = {}
        self.cards: dict[str, AgentCard] = {}
        self.agents: str = ""
        
        # Track completed requests to prevent multiple calls
        self.completed_requests = set()
        
        self.system_prompt = (
            system_prompt
            if system_prompt
            else self.get_default_system_prompt()
        )

        # Create the send_message_tool using the tool decorator
        @tool
        async def send_message_tool(agent_name: str, task: str) -> str:
            """Tool function for sending messages to remote agents.
            
            Args:
                agent_name: The name of the agent to send the message to
                task: The task or message to send to the agent
                
            Returns:
                The response from the agent
            """
            return await self._send_message_impl(agent_name, task)
        
        self.tools = [current_time, send_message_tool]

        # Initialize agent with memory hook if provided
        if self.memory_hook:
            self.agent = Agent(
                model=self.model,
                system_prompt=self.system_prompt,
                tools=self.tools,
                hooks=[self.memory_hook],
            )
        else:
            self.agent = Agent(
                model=self.model,
                system_prompt=self.system_prompt,
                tools=self.tools,
            )
    
    def get_default_system_prompt(self) -> str:
        # Use getattr to safely access self.agents, defaulting to "No agents discovered yet" if not set
        available_agents = getattr(self, 'agents', 'No agents discovered yet')
        
        return f"""
        Role: You are the Lead NetOps Orchestrator, an expert triage and coordination agent for network operations and troubleshooting. Your primary function is to understand user requests and route them to the appropriate specialist agent.

        Specialist Agents

        1. Connectivity_Troubleshooting_Agent — A NetOps Connectivity Troubleshooting AI assistant specialized in diagnosing and fixing network connectivity issues. This agent has access to powerful tools via AgentCore Gateway for:
           - Testing connectivity between hosts (ping, telnet, nc)
           - DNS resolution and validation
           - Network path analysis
           - Security group and firewall rule verification
           - Route table analysis
           - Network ACL validation
           - VPC peering and transit gateway connectivity

        2. Performance_Agent — A NetOps Performance Analysis AI assistant specialized in AWS network performance monitoring and troubleshooting. This agent has access to three powerful tools via AgentCore Gateway:
        
        1. **FlowMonitorAnalysis** (analyze_network_flow_monitor):
           - Analyzes all Network Flow Monitors in a region and AWS account
           - Provides network health indicators and traffic summary data for each monitor
           - Shows detailed metrics: data_transferred_average_bytes, retransmission_timeouts_sum, retransmissions_sum, round_trip_time_minimum_ms
           - Returns individual results for each monitor with local/remote resources
        
        2. **TrafficMirrorLogs** (analyze_traffic_mirroring_logs):
           - Extracts and analyzes PCAP files from traffic mirroring S3 bucket
           - Performs deep packet analysis using tshark on TrafficMirroringTargetInstance
           - Identifies TCP retransmissions, connection issues, performance stats, and high latency
           - Provides comprehensive network performance insights from captured traffic
        
        3. **FixRetransmissions** (fix_retransmissions):
           - Automatically fixes TCP retransmission issues
           - Restores optimal TCP settings (buffer sizes, window scaling, timeouts)
           - Removes network impairment (packet loss and delay via tc qdisc)
           - Validates changes and monitors impact on retransmission rates

        Core Directives

        Request Routing Rules:

        Route to Connectivity_Troubleshooting_Agent for:
        - Connectivity checks between hosts (can you check connectivity between X and Y)
        - DNS resolution issues
        - Network reachability problems
        - Security group and firewall diagnostics
        - Routing and VPC connectivity issues
        - Cannot connect or cannot reach errors
        - Ping, telnet, or basic network testing requests

        Route to Performance_Agent for:
        - Network performance analysis and troubleshooting
        - VPC Flow Logs monitoring and analysis
        - Traffic mirroring setup and PCAP analysis
        - TCP retransmission and connection issues
        - Network Flow Monitor analysis
        - CloudWatch metrics and performance data
        - Network monitoring infrastructure setup
        - Slow connection or high latency issues

        Parameter Collection: Format requests appropriately for each agent:

        Connectivity_Troubleshooting_Agent Example requests:
        - "Check connectivity between reporting.examplecorp.com and database.examplecorp.com"
        - "Test if server A can reach server B on port 3306"
        - "Diagnose DNS resolution for database.examplecorp.com"
        - "Verify security group rules between these two hosts"
        - "Check routing between VPC A and VPC B"

        Performance_Agent Example requests:
        - "Analyze Network Flow Monitors in us-east-1 for account 123456789012"
        - "Show me detailed traffic metrics for all monitors including retransmissions"
        - "Analyze traffic mirroring logs and perform deep PCAP analysis"
        - "Check for TCP retransmissions in the captured traffic data"
        - "Fix the retransmission issues on the bastion server"
        - "Restore optimal TCP settings and remove network impairment"

        Analysis Results Processing: Ensure you capture and present complete results from specialist agents:

        From Connectivity_Troubleshooting_Agent:
        - Connectivity test results (ping, telnet, nc)
        - DNS resolution results
        - Security group analysis
        - Route table findings
        - Network path verification
        - Detailed diagnostic steps taken
        - Recommendations for fixing connectivity issues

        From Performance_Agent:
        - Network Flow Monitor analysis with detailed traffic summaries per monitor
        - Individual monitor metrics: data transferred, retransmissions, timeouts, RTT
        - Network health indicators (Healthy/Warning/Critical/Degraded)
        - **Deep tshark Analysis Results** including:
          * Complete file names of analyzed PCAP files
          * TCP retransmission detection and analysis per file
          * Connection issues (RST/FIN flags) identification per file
          * Performance statistics (I/O stats, TCP conversations)
          * High latency detection (packets with >100ms delta)
          * S3 paths to detailed analysis results under 'analyzed-content/' directory
          * Comprehensive summary with critical issues and affected connections
        - TCP configuration fix results and validation
        
        **CRITICAL**: When the Performance Agent returns analyze_traffic_mirroring_logs results, you MUST present:
        1. The exact file names of PCAP files analyzed (e.g., "vpcflowlogs-xxx.pcap")
        2. The detailed tshark analysis results for each file
        3. The S3 paths where detailed analysis was uploaded
        4. The complete traffic mirroring logs analysis summary
        Do NOT summarize or omit the Deep tshark Analysis Results - relay them in full detail.

        User Interaction Flow:
        1. **Analyze Request**: Understand whether this is a connectivity or performance issue
        2. **Determine Routing**: Based on request type, decide which specialist agent to contact
        3. **Collect Requirements**: Gather necessary parameters (specialist agents can handle incomplete details)
        4. **Route to Specialist**: Send properly formatted request to Connectivity_Agent or Performance_Agent
        5. **Process Results**: Analyze and summarize the specialist agent's findings
        6. **Present Insights**: Deliver actionable network troubleshooting insights
        7. **Follow-up**: Offer additional analysis or recommendations

        Communication Style:
        - Be direct and technical when discussing network operations
        - Use bullet points for clarity
        - Provide specific metrics and data when available
        - Always relay complete analysis results from specialist agents
        - Do not ask for permission before contacting specialist agents
        - Present detailed results from each tool or test
        - CRITICAL: Do NOT use emojis in any responses - use plain text only

        Agent Naming: Always use exact agent names when sending messages via send_message_tool:
        - "Connectivity_Troubleshooting_Agent" for connectivity checks
        - "Performance_Agent" for performance analysis

        Today's Date (YYYY-MM-DD): {datetime.now().strftime("%Y-%m-%d")}

        <Available Agents> {available_agents} </Available Agents>
        """
    
    async def _async_init_components(self, remote_agent_addresses: List[str]):
        """
        This function gets the agents in the A2A remote agent addresses and then 
        gets the agent card for each, establishes a remote connection and then provides the
        information about the agents.
        """
        print(f"🔍 Attempting to connect to {len(remote_agent_addresses)} remote agents...")
        logger.info(f"Starting connection process to {len(remote_agent_addresses)} remote agents")
        
        # Create HTTP client with proper headers and authentication
        headers = {
            "User-Agent": "A2A-Collaborator-Agent/1.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.bearer_token}"
        }
        
        logger.debug(f"HTTP headers configured: {headers}")
        
        # Enhanced timeout and retry configuration
        timeout_config = httpx.Timeout(
            connect=120.0, # 2 minutes to establish connection (increased from 30s)
            read=1800.0,   # 30 minutes to read response (increased from 15 minutes)
            write=120.0,   # 2 minutes to write request (increased from 30s)
            pool=300.0     # 5 minutes for pool operations (increased from 2 minutes)
        )
        
        async with httpx.AsyncClient(
            timeout=timeout_config,
            headers=headers,
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        ) as client:
            connection_results = []
            
            for i, address in enumerate(remote_agent_addresses, 1):
                print(f"🔗 [{i}/{len(remote_agent_addresses)}] Connecting to: {address}")
                logger.info(f"Attempting connection {i}/{len(remote_agent_addresses)} to {address}")
                
                # Test basic connectivity first with detailed network diagnostics
                try:
                    logger.debug(f"🔍 Testing basic connectivity to {address}")
                    logger.debug(f"🌐 Attempting health check: {address}/health")
                    
                    start_time = time.time()
                    test_response = await client.get(f"{address}/health", timeout=120.0)
                    response_time = time.time() - start_time
                    
                    logger.info(f"✅ Health check successful: {test_response.status_code} ({response_time:.2f}s)")
                    logger.debug(f"📊 Health response headers: {dict(test_response.headers)}")
                    logger.debug(f"📄 Health response body: {test_response.text[:200]}...")
                    
                except httpx.ConnectError as conn_error:
                    logger.error(f"🔌 Connection error during health check for {address}: {conn_error}")
                    logger.error(f"   This indicates the ALB/service is not reachable or not running")
                except httpx.TimeoutException as timeout_error:
                    logger.error(f"⏰ Timeout during health check for {address}: {timeout_error}")
                    logger.error(f"   This indicates the ALB/service is slow to respond or overloaded")
                except httpx.HTTPStatusError as http_error:
                    logger.warning(f"❌ HTTP error during health check for {address}: {http_error.response.status_code}")
                    logger.warning(f"   Response: {http_error.response.text[:200]}...")
                except Exception as health_error:
                    logger.warning(f"⚠️ Unexpected health check error for {address}: {health_error}")
                    logger.warning(f"   Error type: {type(health_error).__name__}")
                    # Continue anyway, health endpoint might not exist
                
                card_resolver = A2ACardResolver(client, address)
                
                try:
                    print(f"📋 Getting agent card from {address}...")
                    agent_card_url = f"{address}/.well-known/agent-card.json"
                    logger.debug(f"🎯 Requesting agent card from {agent_card_url}")
                    
                    # Add retry logic for agent card retrieval with detailed logging
                    max_retries = 3
                    retry_delay = 2
                    
                    for attempt in range(max_retries):
                        try:
                            logger.info(f"🔄 Agent card retrieval attempt {attempt + 1}/{max_retries}")
                            logger.debug(f"📡 Making request to: {agent_card_url}")
                            
                            start_time = time.time()
                            card = await card_resolver.get_agent_card()
                            response_time = time.time() - start_time
                            
                            logger.info(f"✅ Successfully retrieved agent card on attempt {attempt + 1} ({response_time:.2f}s)")
                            logger.debug(f"📋 Agent card data: name={card.name}, description={card.description}")
                            break
                            
                        except httpx.ConnectError as conn_error:
                            logger.error(f"🔌 Connection error on attempt {attempt + 1}: {conn_error}")
                            logger.error(f"   Cannot establish connection to {address}")
                            if attempt < max_retries - 1:
                                logger.info(f"⏳ Retrying in {retry_delay} seconds...")
                                await asyncio.sleep(retry_delay)
                                retry_delay *= 2
                            else:
                                raise conn_error
                                
                        except httpx.TimeoutException as timeout_error:
                            logger.error(f"⏰ Timeout error on attempt {attempt + 1}: {timeout_error}")
                            logger.error(f"   Request to {agent_card_url} timed out")
                            if attempt < max_retries - 1:
                                logger.info(f"⏳ Retrying in {retry_delay} seconds...")
                                await asyncio.sleep(retry_delay)
                                retry_delay *= 2
                            else:
                                raise timeout_error
                                
                        except httpx.HTTPStatusError as http_error:
                            logger.error(f"❌ HTTP {http_error.response.status_code} error on attempt {attempt + 1}")
                            logger.error(f"   URL: {agent_card_url}")
                            logger.error(f"   Response: {http_error.response.text[:500]}...")
                            logger.error(f"   Headers: {dict(http_error.response.headers)}")
                            if attempt < max_retries - 1:
                                logger.info(f"⏳ Retrying in {retry_delay} seconds...")
                                await asyncio.sleep(retry_delay)
                                retry_delay *= 2
                            else:
                                raise http_error
                                
                        except Exception as retry_error:
                            logger.error(f"🚨 Unexpected error on attempt {attempt + 1}: {retry_error}")
                            logger.error(f"   Error type: {type(retry_error).__name__}")
                            logger.error(f"   Error details: {str(retry_error)}")
                            if attempt < max_retries - 1:
                                logger.info(f"⏳ Retrying in {retry_delay} seconds...")
                                await asyncio.sleep(retry_delay)
                                retry_delay *= 2
                            else:
                                raise retry_error
                    
                    print(f"✅ Successfully got agent card: {card.name} - {card.description}")
                    logger.info(f"Agent card details - Name: {card.name}, Description: {card.description}")
                    
                    remote_connection = RemoteAgentConnections(
                        agent_card=card, agent_url=address
                    )
                    self.remote_agent_connections[card.name] = remote_connection
                    self.cards[card.name] = card
                    print(f"✅ Successfully registered agent: {card.name}")
                    logger.info(f"Successfully registered agent: {card.name}")
                    
                    connection_results.append({
                        "address": address,
                        "status": "success",
                        "agent_name": card.name,
                        "description": card.description
                    })
                    
                except httpx.ConnectError as e:
                    error_msg = f"CONNECTION ERROR: Failed to connect to {address}"
                    print(f"❌ {error_msg}: {e}")
                    logger.error(f"🔌 {error_msg}")
                    logger.error(f"   Connection details: {str(e)}")
                    logger.error(f"   This usually means:")
                    logger.error(f"   - ALB is not running or not accessible")
                    logger.error(f"   - Security groups are blocking traffic")
                    logger.error(f"   - Network connectivity issues")
                    logger.error(f"   - DNS resolution problems")
                    connection_results.append({
                        "address": address,
                        "status": "connection_error",
                        "error": str(e),
                        "error_type": "ConnectError"
                    })
                except httpx.TimeoutException as e:
                    error_msg = f"TIMEOUT ERROR: Request to {address} timed out"
                    print(f"⏰ {error_msg}: {e}")
                    logger.error(f"⏰ {error_msg}")
                    logger.error(f"   Timeout details: {str(e)}")
                    logger.error(f"   This usually means:")
                    logger.error(f"   - ALB is overloaded or slow to respond")
                    logger.error(f"   - Backend services are not healthy")
                    logger.error(f"   - Network latency issues")
                    logger.error(f"   - ECS tasks are not running properly")
                    connection_results.append({
                        "address": address,
                        "status": "timeout_error",
                        "error": str(e),
                        "error_type": "TimeoutException"
                    })
                except httpx.HTTPStatusError as e:
                    error_msg = f"HTTP STATUS ERROR: {e.response.status_code} from {address}"
                    print(f"❌ {error_msg}: {e}")
                    print(f"   Response content: {e.response.text[:500]}...")
                    logger.error(f"❌ {error_msg}")
                    logger.error(f"   Status code: {e.response.status_code}")
                    logger.error(f"   Response headers: {dict(e.response.headers)}")
                    logger.error(f"   Response body: {e.response.text[:1000]}...")
                    logger.error(f"   Request URL: {e.request.url}")
                    logger.error(f"   Request method: {e.request.method}")
                    
                    if e.response.status_code == 503:
                        logger.error(f"   HTTP 503 Service Unavailable usually means:")
                        logger.error(f"   - ALB has no healthy targets")
                        logger.error(f"   - ECS service is not running")
                        logger.error(f"   - Health checks are failing")
                        logger.error(f"   - Backend services are down")
                    elif e.response.status_code == 404:
                        logger.error(f"   HTTP 404 Not Found usually means:")
                        logger.error(f"   - Agent card endpoint is not implemented")
                        logger.error(f"   - Wrong URL path")
                        logger.error(f"   - Service routing issues")
                    
                    connection_results.append({
                        "address": address,
                        "status": "http_error",
                        "status_code": e.response.status_code,
                        "error": str(e),
                        "response_text": e.response.text[:500],
                        "error_type": "HTTPStatusError"
                    })
                except Exception as e:
                    error_msg = f"GENERAL ERROR: Failed to initialize connection for {address}"
                    print(f"❌ {error_msg}: {e}")
                    logger.error(f"🚨 {error_msg}")
                    logger.error(f"   Error type: {type(e).__name__}")
                    logger.error(f"   Error details: {str(e)}")
                    logger.error(error_msg, exc_info=True)
                    connection_results.append({
                        "address": address,
                        "status": "general_error",
                        "error": str(e),
                        "error_type": type(e).__name__
                    })

        # Log detailed connection summary
        successful_connections = len(self.cards)
        total_attempts = len(remote_agent_addresses)
        
        print(f"🎯 Successfully connected to {successful_connections} out of {total_attempts} agents")
        logger.info(f"Connection summary: {successful_connections}/{total_attempts} successful")
        
        # Log detailed results
        for result in connection_results:
            if result["status"] == "success":
                logger.info(f"✅ {result['address']} -> {result['agent_name']}: {result['description']}")
            else:
                logger.error(f"❌ {result['address']} -> {result['status']}: {result.get('error', 'Unknown error')}")
        
        if self.cards:
            print("📝 Registered agents:")
            for name, card in self.cards.items():
                print(f"  - {name}: {card.description}")
                logger.info(f"Registered agent: {name} - {card.description}")
        else:
            print("⚠️  No agents were successfully registered")
            logger.warning("No agents were successfully registered - agent will operate in standalone mode")

        agent_info = [
            json.dumps({"name": card.name, "description": card.description})
            for card in self.cards.values()
        ]
        logger.debug(f"Agent info JSON: {agent_info}")
        self.agents = "\n".join(agent_info) if agent_info else "No agents found"
        
        # Update system prompt with discovered agents
        self.system_prompt = self.get_default_system_prompt()
        self.agent.system_prompt = self.system_prompt
        logger.info("System prompt updated with discovered agents")
    
    @classmethod
    async def create(
        cls,
        remote_agent_addresses: List[str],
        bearer_token: str,
        memory_hook: HostMemoryHook = None,
    ):
        instance = cls(bearer_token=bearer_token, memory_hook=memory_hook)
        await instance._async_init_components(remote_agent_addresses)
        return instance

    async def stream(self, user_query: str):
        """Stream the agent's response to a given query with rate limiting."""
        async with self._bedrock_semaphore:
            # Implement minimum delay between API calls
            current_time = time.time()
            time_since_last_call = current_time - self._last_api_call_time
            
            if time_since_last_call < self._min_delay_between_calls:
                delay = self._min_delay_between_calls - time_since_last_call
                logger.info(f"⏳ Rate limiting: waiting {delay:.2f}s before next API call")
                await asyncio.sleep(delay)
            
            self._last_api_call_time = time.time()
            
            try:
                retry_count = 0
                max_retries = 3
                base_delay = 2.0
                
                while retry_count <= max_retries:
                    try:
                        async for event in self.agent.stream_async(user_query):
                            if "data" in event:
                                yield event["data"]
                        break  # Success, exit retry loop
                        
                    except Exception as e:
                        error_str = str(e).lower()
                        
                        # Check if it's a throttling error
                        if "throttling" in error_str or "too many requests" in error_str:
                            retry_count += 1
                            
                            if retry_count > max_retries:
                                logger.error(f"❌ Max retries ({max_retries}) exceeded for throttling error")
                                yield f"Error: Request throttled after {max_retries} retries. Please wait a moment and try again."
                                break
                            
                            # Exponential backoff: 2s, 4s, 8s
                            backoff_delay = base_delay * (2 ** (retry_count - 1))
                            logger.warning(f"⚠️ Throttling detected. Retry {retry_count}/{max_retries} after {backoff_delay}s delay")
                            yield f"\n⏳ Request throttled. Retrying in {backoff_delay}s... (attempt {retry_count}/{max_retries})\n"
                            
                            await asyncio.sleep(backoff_delay)
                            self._last_api_call_time = time.time()
                        else:
                            # Non-throttling error, don't retry
                            logger.error(f"❌ Non-throttling error: {e}")
                            yield f"Error: {e}"
                            break
                            
            except Exception as e:
                logger.error(f"❌ Unexpected error in stream: {e}")
                yield f"Error: {e}"

    async def _send_message_impl(self, agent_name: str, task: str):
        """Implementation method for sending messages to remote agents with retry logic."""
        
        # Create a unique key for this request to prevent duplicate calls
        request_key = f"{agent_name}:{hash(task)}"
        
        # Check if we've already processed this exact request
        if request_key in self.completed_requests:
            logger.info(f"🚫 Request already completed for {agent_name} with task hash {hash(task)}")
            return "Request already processed - avoiding duplicate call to prevent multiple invocations"
        
        if agent_name not in self.remote_agent_connections:
            return f"Agent {agent_name} not found"
        
        client = self.remote_agent_connections[agent_name]
        if not client:
            return f"Client not available for {agent_name}"

        # Mark this request as being processed
        self.completed_requests.add(request_key)
        logger.info(f"📝 Marked request as processing: {request_key}")

        # Generate IDs for the message
        context_id = str(uuid.uuid4())
        message_id = str(uuid.uuid4())

        payload = {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": task}],
                "messageId": message_id,
                "contextId": context_id,
            },
        }

        message_request = SendMessageRequest(
            id=message_id, params=MessageSendParams.model_validate(payload)
        )
        
        # Reduced retry logic for A2A communication to prevent excessive calls
        max_retries = 1  # Reduced from 3 to 1 to minimize duplicate calls
        base_delay = 2.0
        
        for retry_count in range(max_retries + 1):
            try:
                # Add delay before retry attempts
                if retry_count > 0:
                    backoff_delay = base_delay * (2 ** (retry_count - 1))
                    logger.info(f"⏳ Retrying A2A message to {agent_name} after {backoff_delay}s (attempt {retry_count + 1}/{max_retries + 1})")
                    await asyncio.sleep(backoff_delay)
                
                send_response: SendMessageResponse = await client.send_message(message_request)
                logger.debug(f"✅ A2A message sent successfully to {agent_name}")

                if not isinstance(
                    send_response.root, SendMessageSuccessResponse
                ) or not isinstance(send_response.root.result, Task):
                    logger.warning(f"⚠️ Non-success response from {agent_name}, but treating as completed to prevent retries")
                    return "Received a non-success or non-task response. Request completed to prevent duplicate calls."

                response_content = send_response.root.model_dump_json(exclude_none=True)
                json_content = json.loads(response_content)

                resp = []
                if json_content.get("result", {}).get("artifacts"):
                    for artifact in json_content["result"]["artifacts"]:
                        if artifact.get("parts"):
                            resp.extend(artifact["parts"])
                
                result = json.dumps(resp, indent=2) if resp else "No response received"
                logger.info(f"✅ Successfully completed request {request_key}")
                return result
                
            except Exception as e:
                error_str = str(e).lower()
                
                # More restrictive retry logic - only retry on very specific errors and only once
                if ("throttling" in error_str or "too many requests" in error_str) and retry_count < max_retries:
                    logger.warning(f"⚠️ A2A communication error (attempt {retry_count + 1}/{max_retries + 1}): {e}")
                    continue  # Retry only for throttling
                else:
                    # Final attempt failed or non-retryable error
                    logger.error(f"❌ A2A message to {agent_name} failed: {e}")
                    # Still mark as completed to prevent further attempts
                    error_msg = f"Error sending message to {agent_name}: {str(e)}"
                    logger.info(f"✅ Marked failed request as completed to prevent retries: {request_key}")
                    return error_msg
        
        final_error = f"Error: Failed to send message to {agent_name} after {max_retries + 1} attempts"
        logger.info(f"✅ Marked failed request as completed after all retries: {request_key}")
        return final_error


async def host_agent_task(user_message: str, session_id: str, actor_id: str):
    """Task function for processing user messages with the host agent."""
    agent = HostAgentContext.get_agent_ctx()
    response_queue = HostAgentContext.get_response_queue_ctx()
    gateway_access_token = HostAgentContext.get_gateway_token_ctx()

    if not gateway_access_token:
        raise RuntimeError("Gateway Access token is none")
    
    try:
        if agent is None:
            memory_hook = HostMemoryHook(
                memory_client=memory_client,
                memory_id=get_ssm_parameter("/a2a/app/performance/agentcore/memory_id"),
                actor_id=actor_id,
                session_id=session_id,
            )

            # Get agent URLs from config
            agent_urls = config['servers']
            
            agent = await HostAgent.create(
                remote_agent_addresses=agent_urls,
                bearer_token=gateway_access_token,
                memory_hook=memory_hook,
            )

            HostAgentContext.set_agent_ctx(agent)

        async for chunk in agent.stream(user_query=user_message):
            await response_queue.put(chunk)

    except Exception as e:
        logger.exception("Host agent execution failed.")
        await response_queue.put(f"Error: {str(e)}")
    finally:
        await response_queue.finish()


@app.entrypoint
async def invoke(payload, context):
    """BedrockAgentCore entrypoint for the host agent."""
    if not HostAgentContext.get_response_queue_ctx():
        HostAgentContext.set_response_queue_ctx(HostStreamingQueue())

    if not HostAgentContext.get_gateway_token_ctx():
        HostAgentContext.set_gateway_token_ctx(await get_gateway_access_token())

    user_message = payload["prompt"]
    actor_id = payload["actor_id"]
    session_id = context.session_id

    if not session_id:
        raise Exception("Context session_id is not set")

    task = asyncio.create_task(
        host_agent_task(
            user_message=user_message,
            session_id=session_id,
            actor_id=actor_id,
        )
    )

    response_queue = HostAgentContext.get_response_queue_ctx()

    async def stream_output():
        async for item in response_queue.stream():
            yield item
        await task  # Ensure task completion

    return stream_output()


# Handler for container environments
def handler(event, context):
    """Lambda container handler"""
    return app.handle(event, context)


def _get_initialized_host_agent_sync():
    """Synchronously creates and initializes the HostAgent for backwards compatibility."""
    async def _async_main():
        print(f"Going to connect to agent running on the following ports: {str(config['servers'])}")
        agent_urls = config['servers']
        
        try:
            # Try to get access token for sync initialization
            gateway_access_token = await get_gateway_access_token()
        except Exception as e:
            print(f"Warning: Could not get access token during startup initialization: {e}")
            print("This is expected during container startup. Agent will initialize properly during runtime.")
            # Return None to indicate initialization should be deferred to runtime
            return None
        
        print("initializing host agent")
        hosting_agent_instance = await HostAgent.create(
            remote_agent_addresses=agent_urls,
            bearer_token=gateway_access_token,
        )
        print("HostAgent initialized")
        return hosting_agent_instance

    try:
        return asyncio.run(_async_main())
    except RuntimeError as e:
        if "asyncio.run() cannot be called from a running event loop" in str(e):
            print(
                f"Warning: Could not initialize HostAgent with asyncio.run(): {e}. "
                "This can happen if an event loop is already running (e.g., in Jupyter). "
                "Consider initializing HostAgent within an async function in your application."
            )
        else:
            raise

# For backwards compatibility
root_agent = None
try:
    root_agent = _get_initialized_host_agent_sync()
    if root_agent is None:
        print("HostAgent initialization deferred to runtime due to missing access token context")
except Exception as e:
    print(f"Could not initialize root_agent: {e}")
    print("This is expected during container startup. Agent will initialize properly during runtime.")

if __name__ == "__main__":
    app.run()
