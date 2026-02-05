"""
AgentCore Agent Evaluation Pipeline

This module implements the comprehensive LLM-as-a-Judge evaluation framework for AgentCore agents.
Uses dynamic configuration instead of hardcoded values.
"""

import asyncio
import boto3
import json
import logging
import numpy as np
import os
import uuid
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Dict, List, Optional, Any

# 기본 모델 ID (환경변수로 오버라이드 가능)
DEFAULT_MODEL_ID = "global.anthropic.claude-opus-4-5-20251101-v1:0"

# Import AgentCore client and configuration loader
from .agentcore_client import AgentCoreClient
from .config_loader import get_config, get_config_loader, AgentConfig

# Import comprehensive test scenarios
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
from configs.test_scenarios.agent_test_scenarios import AgentTestSuite

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class TestCase:
    id: str
    query: str
    category: str
    expected_tools: List[str]
    expected_criteria: Dict[str, Any]
    description: str


class CloudWatchToolDetector:
    """Multi-layer tool detection system using CloudWatch"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or get_config()
        self.cloudwatch_config = self.config.get('cloudwatch', {})
        self.logs_client = boto3.client('logs')
        self.cloudwatch_client = boto3.client('cloudwatch')
        
        # Load configurable parameters
        self.max_query_attempts = self.cloudwatch_config.get('max_query_attempts', 30)
        self.query_timeout_seconds = self.cloudwatch_config.get('query_timeout_seconds', 60)
        self.log_propagation_delay = self.cloudwatch_config.get('log_propagation_delay_seconds', 5)
    
    async def detect_tools_layer1_insights(self, session_id: str, log_group: str, 
                                         start_time: datetime, end_time: datetime) -> List[Dict]:
        """Layer 1: Primary detection via CloudWatch Logs Insights API"""
        query = f"""
        fields @timestamp, @message
        | filter @message like /{session_id}/
        | filter @message like /toolResult/ or @message like /toolUse/
        | sort @timestamp desc
        | limit 100
        """
        try:
            response = self.logs_client.start_query(
                logGroupName=log_group,
                startTime=int(start_time.timestamp()),
                endTime=int(end_time.timestamp()),
                queryString=query
            )
            return await self._poll_query_results(response['queryId'])
        except Exception as e:
            logger.warning(f"Layer 1 detection failed: {e}")
            return await self.detect_tools_layer2_filter(session_id, log_group, start_time, end_time)
    
    async def detect_tools_layer2_filter(self, session_id: str, log_group: str,
                                       start_time: datetime, end_time: datetime) -> List[Dict]:
        """Layer 2: Fallback using filter_log_events"""
        try:
            response = self.logs_client.filter_log_events(
                logGroupName=log_group,
                startTime=int(start_time.timestamp() * 1000),
                endTime=int(end_time.timestamp() * 1000),
                filterPattern=f'"{session_id}" "toolResult"'
            )
            return self._parse_filter_events(response.get('events', []))
        except Exception as e:
            logger.warning(f"Layer 2 detection failed: {e}")
            return await self.detect_tools_layer3_content(session_id)
    
    async def detect_tools_layer3_content(self, session_id: str) -> List[Dict]:
        """Layer 3: Content-based detection when logs unavailable"""
        # Placeholder for content-based tool detection
        return []
    
    async def _poll_query_results(self, query_id: str) -> List[Dict]:
        """Poll CloudWatch Logs Insights query results"""
        max_attempts = 30
        for attempt in range(max_attempts):
            try:
                response = self.logs_client.get_query_results(queryId=query_id)
                if response['status'] == 'Complete':
                    return self._parse_insights_results(response.get('results', []))
                elif response['status'] == 'Failed':
                    logger.error(f"Query failed: {response}")
                    return []
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Query polling failed: {e}")
                return []
        return []
    
    def _parse_insights_results(self, results: List) -> List[Dict]:
        """Parse CloudWatch Logs Insights results"""
        parsed_tools = []
        for result in results:
            try:
                # Extract tool information from log entries
                message_field = next((field for field in result if field['field'] == '@message'), None)
                if message_field:
                    message = message_field['value']
                    if 'toolUse' in message or 'toolResult' in message:
                        parsed_tools.append({
                            'toolName': self._extract_tool_name(message),
                            'timestamp': next((field['value'] for field in result if field['field'] == '@timestamp'), ''),
                            'raw_message': message
                        })
            except Exception as e:
                logger.warning(f"Failed to parse result: {e}")
        return parsed_tools
    
    def _parse_filter_events(self, events: List) -> List[Dict]:
        """Parse filter_log_events results"""
        parsed_tools = []
        for event in events:
            try:
                message = event.get('message', '')
                if 'toolUse' in message or 'toolResult' in message:
                    parsed_tools.append({
                        'toolName': self._extract_tool_name(message),
                        'timestamp': event.get('timestamp', ''),
                        'raw_message': message
                    })
            except Exception as e:
                logger.warning(f"Failed to parse event: {e}")
        return parsed_tools
    
    def _extract_tool_name(self, message: str) -> str:
        """Extract tool name from log message"""
        # Implement tool name extraction logic
        if 'dns-resolve' in message.lower():
            return 'dns-resolve'
        elif 'connectivity' in message.lower():
            return 'connectivity'
        elif 'analyze_network_flow_monitor' in message.lower():
            return 'analyze_network_flow_monitor'
        elif 'analyze_traffic_mirroring_logs' in message.lower():
            return 'analyze_traffic_mirroring_logs'
        elif 'fix_retransmissions' in message.lower():
            return 'fix_retransmissions'
        elif 'send_message_tool' in message.lower():
            return 'send_message_tool'
        else:
            return 'unknown_tool'
    
    def _handle_complex_log_structures(self, log_entry: Dict) -> Dict:
        """Handle various log formats including @message wrapper"""
        if '@message' in log_entry:
            # Logs Insights format with @message wrapper
            message_content = log_entry['@message']
            if isinstance(message_content, dict):
                return self._extract_nested_content(message_content)
        return log_entry
    
    def _extract_nested_content(self, content: Dict) -> Dict:
        """Extract content from nested log structures"""
        # Implementation for handling nested log content
        return content


class LLMJudge:
    """LLM-as-a-Judge evaluation using Claude Sonnet 4"""

    def __init__(self, judge_model: str = None):
        # 환경변수 > 파라미터 > 기본값 순으로 모델 ID 결정
        if judge_model is None:
            judge_model = os.environ.get('BEDROCK_MODEL_ID', DEFAULT_MODEL_ID)
        self.judge_model = judge_model
        # Get region from config or use default
        config = get_config()
        region = config.get('aws', {}).get('region', 'us-east-1')
        self.bedrock_client = boto3.client('bedrock-runtime', region_name=region)
        self.evaluation_dimensions = [
            'helpfulness', 'accuracy', 'clarity', 'professionalism', 'completeness'
        ]
    
    async def evaluate_response(self, test_result: Dict) -> Dict[str, Any]:
        """Evaluate agent response using 5-dimensional rubric"""
        evaluation_prompt = self._create_evaluation_prompt(
            test_result.get('query', ''),
            test_result.get('response', ''),
            test_result.get('detected_tools', []),
            test_result.get('expected_tools', [])
        )
        
        try:
            judge_response = await self._invoke_judge_llm(evaluation_prompt)
            scores = self._parse_judge_scores(judge_response)
            
            return {
                'test_case_id': test_result.get('test_case_id'),
                'session_id': test_result.get('session_id'),
                'scores': scores,
                'overall_score': self._calculate_overall_score(scores),
                'tool_usage_score': self._calculate_tool_usage_score(
                    test_result.get('detected_tools', []), 
                    test_result.get('expected_tools', [])
                ),
                'judge_feedback': judge_response,
                'evaluation_timestamp': datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Judge evaluation failed: {e}")
            return self._create_evaluation_error(test_result, str(e))
    
    def _create_evaluation_prompt(self, query: str, response: str, 
                                detected_tools: List, expected_tools: List) -> str:
        """Generate structured 5-dimensional evaluation prompt"""
        return f"""Please evaluate this network operations agent response on the following five dimensions:

1. Helpfulness (1-5): How well does the response address the user's network operations needs?
2. Accuracy (1-5): Is the technical information provided factually correct?
3. Clarity (1-5): Is the response well-structured and easy to understand for network operations staff?
4. Professionalism (1-5): Does the response maintain appropriate technical tone and language?
5. Completeness (1-5): Are all aspects of the network operations query addressed?

Additional Context:
- User Query: {query}
- Agent Response: {response}
- Tools Expected: {expected_tools}
- Tools Detected: {[tool.get('toolName', 'unknown') for tool in detected_tools]}

Provide scores as JSON with explanations:
{{
    "helpfulness": {{"score": X, "explanation": "..."}},
    "accuracy": {{"score": X, "explanation": "..."}},
    "clarity": {{"score": X, "explanation": "..."}},
    "professionalism": {{"score": X, "explanation": "..."}},
    "completeness": {{"score": X, "explanation": "..."}}
}}"""
    
    async def _invoke_judge_llm(self, prompt: str) -> str:
        """Invoke Bedrock Claude model for evaluation"""
        try:
            response = self.bedrock_client.invoke_model(
                modelId=self.judge_model,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 2000,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                })
            )
            
            response_body = json.loads(response['body'].read())
            return response_body['content'][0]['text']
            
        except Exception as e:
            logger.error(f"Bedrock invocation failed: {e}")
            raise
    
    def _parse_judge_scores(self, judge_response: str) -> Dict:
        """Parse judge LLM response into structured scores"""
        try:
            # Extract JSON from response
            start_idx = judge_response.find('{')
            end_idx = judge_response.rfind('}') + 1
            if start_idx != -1 and end_idx != -1:
                json_str = judge_response[start_idx:end_idx]
                return json.loads(json_str)
            else:
                # Fallback parsing if JSON not found
                return self._fallback_score_parsing(judge_response)
        except Exception as e:
            logger.warning(f"Score parsing failed: {e}")
            return self._default_scores()
    
    def _fallback_score_parsing(self, response: str) -> Dict:
        """Fallback method to extract scores from response"""
        scores = {}
        for dimension in self.evaluation_dimensions:
            # Look for patterns like "helpfulness: 4" or "Helpfulness (4/5)"
            import re
            pattern = rf"{dimension}.*?(\d+(?:\.\d+)?)"
            match = re.search(pattern, response, re.IGNORECASE)
            if match:
                score = float(match.group(1))
                scores[dimension] = {
                    'score': min(score, 5.0),
                    'explanation': f"Extracted from judge response"
                }
            else:
                scores[dimension] = {
                    'score': 3.0,
                    'explanation': "Could not extract score, using default"
                }
        return scores
    
    def _default_scores(self) -> Dict:
        """Return default scores when parsing fails"""
        return {
            dimension: {
                'score': 3.0,
                'explanation': "Default score due to parsing failure"
            }
            for dimension in self.evaluation_dimensions
        }
    
    def _calculate_overall_score(self, scores: Dict) -> float:
        """Calculate overall score from dimensional scores"""
        if not scores:
            return 0.0
        
        total_score = 0.0
        count = 0
        
        for dimension_scores in scores.values():
            if isinstance(dimension_scores, dict) and 'score' in dimension_scores:
                total_score += dimension_scores['score']
                count += 1
        
        return total_score / count if count > 0 else 0.0
    
    def _calculate_tool_usage_score(self, detected_tools: List, expected_tools: List) -> float:
        """Calculate tool usage accuracy score"""
        if not expected_tools:
            return 5.0  # Perfect score if no tools expected
        
        detected_tool_names = [tool.get('toolName', '') for tool in detected_tools]
        
        # Calculate precision and recall
        true_positives = len(set(detected_tool_names) & set(expected_tools))
        false_positives = len(set(detected_tool_names) - set(expected_tools))
        false_negatives = len(set(expected_tools) - set(detected_tool_names))
        
        precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
        recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0
        
        # F1 score converted to 1-5 scale
        f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
        return f1_score * 5
    
    def _create_evaluation_error(self, test_result: Dict, error: str) -> Dict:
        """Create error result for failed evaluations"""
        return {
            'test_case_id': test_result.get('test_case_id'),
            'session_id': test_result.get('session_id'),
            'scores': self._default_scores(),
            'overall_score': 0.0,
            'tool_usage_score': 0.0,
            'error': error,
            'evaluation_timestamp': datetime.utcnow().isoformat()
        }


class AgentTestRunner:
    """Test runner for executing scenarios against agents"""
    
    def __init__(self, runtime_arn: str, agent_type: str, cognito_config: Dict, log_group: str):
        self.runtime_arn = runtime_arn
        self.agent_type = agent_type
        self.cognito_config = cognito_config
        self.log_group = log_group
        self.agent_client = AgentCoreClient(cognito_config)  # Initialize client immediately
        self.tool_detector = CloudWatchToolDetector()
    
    async def execute_scenario(self, test_case: TestCase) -> Dict[str, Any]:
        """Execute test scenario with comprehensive logging and timing"""
        session_id = self._generate_session_id(test_case.id)
        start_time = datetime.utcnow()
        
        try:
            # Initialize AgentCore client if not already done
            if not self.agent_client:
                self.agent_client = AgentCoreClient(self.cognito_config)
            
            # Log the test message being sent
            logger.info(f"📤 Sending workflow test message to agent")
            logger.info(f"💬 Message: \"{test_case.query}\"")
            
            # Execute agent with session tracking
            response = await self.agent_client.invoke_agent(
                runtime_arn=self.runtime_arn,
                message=test_case.query,
                session_id=session_id
            )
            
            end_time = datetime.utcnow()
            response_time = (end_time - start_time).total_seconds()
            
            # Wait for CloudWatch log propagation
            await asyncio.sleep(5)
            
            # Multi-layer tool detection
            detected_tools = await self.tool_detector.detect_tools_layer1_insights(
                session_id, self.log_group, start_time, end_time
            )
            
            return {
                'test_case_id': test_case.id,
                'session_id': session_id,
                'query': test_case.query,
                'response': response,
                'response_time': response_time,
                'detected_tools': detected_tools,
                'expected_tools': test_case.expected_tools,
                'timestamp': start_time.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Test execution failed for {test_case.id}: {e}")
            return self._create_error_result(test_case, session_id, str(e))
    
    def _generate_session_id(self, test_case_id: str) -> str:
        """Generate unique session ID for log correlation (must be >= 33 chars)"""
        return str(uuid.uuid4())
    
    
    def _create_error_result(self, test_case: TestCase, session_id: str, error: str) -> Dict:
        """Create error result for failed test execution"""
        return {
            'test_case_id': test_case.id,
            'session_id': session_id,
            'query': test_case.query,
            'response': f"ERROR: {error}",
            'response_time': 0.0,
            'detected_tools': [],
            'expected_tools': test_case.expected_tools,
            'error': error,
            'timestamp': datetime.utcnow().isoformat()
        }


class PerformanceAnalyzer:
    """Analyze evaluation results for performance metrics"""
    
    def analyze_evaluation_results(self, results: List[Dict]) -> Dict[str, Any]:
        """Comprehensive analysis of evaluation results"""
        response_times = [r['response_time'] for r in results if 'response_time' in r and r['response_time'] > 0]
        scores = [r.get('evaluation', {}).get('scores', {}) for r in results if 'evaluation' in r]
        
        return {
            'performance_metrics': {
                'median_response_time': np.median(response_times) if response_times else 0,
                'p90_response_time': np.percentile(response_times, 90) if response_times else 0,
                'p95_response_time': np.percentile(response_times, 95) if response_times else 0,
                'average_response_time': np.mean(response_times) if response_times else 0
            },
            'quality_metrics': self._calculate_quality_metrics(scores),
            'tool_usage_patterns': self._analyze_tool_patterns(results),
            'success_rate': self._calculate_success_rate(results),
            'failure_analysis': self._analyze_failures(results)
        }
    
    def _calculate_quality_metrics(self, scores: List[Dict]) -> Dict[str, float]:
        """Calculate average scores across all dimensions"""
        dimensions = ['helpfulness', 'accuracy', 'clarity', 'professionalism', 'completeness']
        avg_scores = {}
        
        for dimension in dimensions:
            dimension_scores = []
            for score_dict in scores:
                if dimension in score_dict and isinstance(score_dict[dimension], dict):
                    if 'score' in score_dict[dimension]:
                        dimension_scores.append(score_dict[dimension]['score'])
            
            avg_scores[dimension] = np.mean(dimension_scores) if dimension_scores else 0.0
        
        avg_scores['overall_average'] = np.mean(list(avg_scores.values()))
        return avg_scores
    
    def _analyze_tool_patterns(self, results: List[Dict]) -> Dict[str, Any]:
        """Analyze tool usage patterns"""
        tool_usage = {}
        for result in results:
            detected_tools = result.get('detected_tools', [])
            for tool in detected_tools:
                tool_name = tool.get('toolName', 'unknown')
                tool_usage[tool_name] = tool_usage.get(tool_name, 0) + 1
        
        return {
            'tool_frequency': tool_usage,
            'most_used_tool': max(tool_usage.items(), key=lambda x: x[1])[0] if tool_usage else None,
            'total_tool_calls': sum(tool_usage.values())
        }
    
    def _calculate_success_rate(self, results: List[Dict]) -> float:
        """Calculate overall success rate"""
        if not results:
            return 0.0
        
        successful_results = sum(1 for r in results if 'error' not in r)
        return (successful_results / len(results)) * 100
    
    def _analyze_failures(self, results: List[Dict]) -> Dict[str, Any]:
        """Analyze failure patterns"""
        failures = [r for r in results if 'error' in r]
        
        failure_types = {}
        for failure in failures:
            error = failure.get('error', 'Unknown error')
            error_type = error.split(':')[0] if ':' in error else error
            failure_types[error_type] = failure_types.get(error_type, 0) + 1
        
        return {
            'total_failures': len(failures),
            'failure_rate': (len(failures) / len(results)) * 100 if results else 0,
            'failure_types': failure_types,
            'most_common_failure': max(failure_types.items(), key=lambda x: x[1])[0] if failure_types else None
        }


class AgentEvaluationPipeline:
    """Main evaluation pipeline orchestrator"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or get_config()
        self.config_loader = get_config_loader()
        
        # Initialize components with configuration
        llm_config = self.config_loader.get_llm_judge_config()
        self.llm_judge = LLMJudge(llm_config.get('model_id', 'global.anthropic.claude-opus-4-5-20251101-v1:0'))
        
        self.performance_analyzer = PerformanceAnalyzer()
        self.agent_clients = {}
        
        # Load agent configurations dynamically
        self.agent_configs = self._load_agent_configs()
    
    def _load_agent_configs(self) -> Dict[str, AgentConfig]:
        """Load agent configurations from config loader"""
        agent_configs = {}
        
        for agent_name in ['TroubleshootingAgent', 'PerformanceAgent', 'CollaboratorAgent']:
            agent_config = self.config_loader.get_agent_config(agent_name)
            if agent_config:
                agent_configs[agent_name] = agent_config
            else:
                logger.warning(f"No configuration found for {agent_name}")
        
        return agent_configs
    
    async def run_comprehensive_evaluation(self) -> Dict[str, Any]:
        """Run complete evaluation pipeline for all dynamically configured agents"""
        
        evaluation_results = {}
        
        # Evaluate each agent using dynamic configuration
        for agent_name, agent_config in self.agent_configs.items():
            logger.info(f"Starting evaluation for {agent_name} with runtime ARN: {agent_config.runtime_arn}")
            
            # Convert AgentConfig to dict format for compatibility
            config = {
                'runtime_arn': agent_config.runtime_arn,
                'agent_type': agent_config.agent_type,
                'cognito_config': agent_config.cognito_config,
                'alb_dns': agent_config.alb_dns,
                'log_group': agent_config.log_group
            }
            
            try:
                # Phase 1: Agent Initialization Testing
                initialization_results = await self._test_agent_initialization(agent_name, config)
                
                # Phase 2: Tool Usage and Workflow Testing  
                workflow_results = await self._test_agent_workflows(agent_name, config)
                
                # Phase 3: Specialized Testing (SKIPPED)
                logger.info(f"Skipping Phase 3: Specialized Testing for {agent_name}")
                specific_results = {
                    'test_status': 'skipped',
                    'message': 'Phase 3: Specialized Testing has been skipped by configuration'
                }
                
                # Phase 4: LLM Judge Evaluation for this agent
                judge_results = await self._run_llm_judge_evaluation(
                    agent_name, initialization_results, workflow_results, specific_results
                )
                
                evaluation_results[agent_name] = {
                    'runtime_arn': config['runtime_arn'],
                    'agent_type': config['agent_type'],
                    'initialization': initialization_results,
                    'workflow': workflow_results,
                    'specific_tests': specific_results,
                    'judge_evaluation': judge_results
                }
                
                logger.info(f"Completed evaluation for {agent_name}")
                
            except Exception as e:
                logger.error(f"Evaluation failed for {agent_name}: {e}")
                evaluation_results[agent_name] = {
                    'runtime_arn': config['runtime_arn'],
                    'agent_type': config['agent_type'],
                    'error': str(e),
                    'status': 'failed'
                }
        
        # Generate comprehensive report
        return self._generate_comprehensive_report(evaluation_results)
    
    async def _test_agent_initialization(self, agent_name: str, config: Dict) -> Dict:
        """Test agent initialization using AgentCore runtime ARN"""
        try:
            # Initialize AgentCore client for this agent
            agentcore_client = AgentCoreClient(config['cognito_config'])
            
            # Test basic invocation to verify agent is accessible
            test_message = "Hello, this is a test message to verify agent accessibility."
            test_session_id = str(uuid.uuid4())
            
            try:
                response = await agentcore_client.invoke_agent(
                    runtime_arn=config['runtime_arn'],
                    message=test_message,
                    session_id=test_session_id
                )
                
                initialization_success = True
                response_text = response[:200] + "..." if len(response) > 200 else response
                
            except Exception as invoke_error:
                logger.warning(f"Agent invocation test failed: {invoke_error}")
                initialization_success = False
                response_text = f"Invocation failed: {str(invoke_error)}"
            
            # Store client for later use
            self.agent_clients[agent_name] = agentcore_client
            
            return {
                'agent_name': agent_name,
                'runtime_arn': config['runtime_arn'],
                'agent_type': config['agent_type'],
                'initialization_success': initialization_success,
                'test_response': response_text,
                'cognito_configured': bool(config['cognito_config'].get('machine_client_id')),
                'log_group': config['log_group']
            }
            
        except Exception as e:
            return {
                'agent_name': agent_name,
                'runtime_arn': config['runtime_arn'],
                'initialization_success': False,
                'error': str(e)
            }
    
    
    async def _test_agent_workflows(self, agent_name: str, config: Dict) -> Dict:
        """Test agent workflow execution with AgentCore runtime invocation"""
        try:
            # Get the AgentCore client for this agent
            if agent_name not in self.agent_clients:
                logger.warning(f"AgentCore client not initialized for {agent_name}")
                return self._create_workflow_error(agent_name, "Client not initialized")
            
            agentcore_client = self.agent_clients[agent_name]
            
            # Create test runner for this agent
            test_runner = AgentTestRunner(
                runtime_arn=config['runtime_arn'],
                agent_type=config['agent_type'],
                cognito_config=config['cognito_config'],
                log_group=config['log_group']
            )
            
            # Load basic test scenarios based on agent type
            test_scenarios = self._get_basic_test_scenarios(agent_name, config['agent_type'])
            
            test_results = []
            passed_tests = 0
            
            for scenario in test_scenarios:
                try:
                    result = await test_runner.execute_scenario(scenario)
                    test_results.append(result)
                    
                    # Check if test passed (basic success criteria)
                    if 'error' not in result and result.get('response'):
                        passed_tests += 1
                        
                except Exception as e:
                    logger.error(f"Scenario execution failed: {e}")
                    test_results.append({
                        'test_case_id': scenario.id,
                        'error': str(e),
                        'status': 'failed'
                    })
            
            return {
                'agent_name': agent_name,
                'runtime_arn': config['runtime_arn'],
                'total_tests': len(test_scenarios),
                'passed_tests': passed_tests,
                'success_rate': (passed_tests / len(test_scenarios)) * 100 if test_scenarios else 0,
                'test_results': test_results,
                'workflow_status': 'completed'
            }
            
        except Exception as e:
            logger.error(f"Workflow testing failed for {agent_name}: {e}")
            return self._create_workflow_error(agent_name, str(e))
    
    def _get_basic_test_scenarios(self, agent_name: str, agent_type: str) -> List[TestCase]:
        """Get comprehensive test scenarios from AgentTestSuite"""
        try:
            # Initialize the comprehensive test suite
            test_suite = AgentTestSuite()
            
            # Get scenarios for the specific agent
            comprehensive_scenarios = test_suite.get_scenarios_by_agent(agent_name)
            
            if not comprehensive_scenarios:
                logger.warning(f"No comprehensive scenarios found for {agent_name}, using fallback basic scenarios")
                return self._get_fallback_basic_scenarios(agent_name, agent_type)
            
            # Convert comprehensive scenarios to TestCase format
            converted_scenarios = []
            for scenario in comprehensive_scenarios:
                test_case = TestCase(
                    id=scenario.id,
                    query=scenario.query,
                    category=scenario.category,
                    expected_tools=scenario.expected_tools,
                    expected_criteria=scenario.validation_criteria,
                    description=scenario.description
                )
                converted_scenarios.append(test_case)
            
            logger.info(f"Loaded {len(converted_scenarios)} comprehensive test scenarios for {agent_name}")
            return converted_scenarios
            
        except Exception as e:
            logger.warning(f"Failed to load comprehensive scenarios for {agent_name}: {e}")
            return self._get_fallback_basic_scenarios(agent_name, agent_type)
    
    def _get_fallback_basic_scenarios(self, agent_name: str, agent_type: str) -> List[TestCase]:
        """Fallback basic test scenarios if comprehensive scenarios fail to load"""
        scenarios = []
        
        if agent_type == "connectivity":
            scenarios.extend([
                TestCase(
                    id="connectivity_basic_1",
                    query="Help me troubleshoot connectivity issues with my EC2 instance",
                    category="basic_troubleshooting",
                    expected_tools=["connectivity", "dns-resolve"],
                    expected_criteria={"helpfulness": 4.0},
                    description="Basic connectivity troubleshooting query"
                ),
                TestCase(
                    id="connectivity_dns_1", 
                    query="My instance cannot resolve DNS names. What should I check?",
                    category="dns_troubleshooting",
                    expected_tools=["dns-resolve"],
                    expected_criteria={"accuracy": 4.0},
                    description="DNS resolution troubleshooting"
                )
            ])
        elif agent_type == "performance":
            scenarios.extend([
                TestCase(
                    id="performance_basic_1",
                    query="Analyze network performance issues in my VPC",
                    category="performance_analysis",
                    expected_tools=["analyze_network_flow_monitor", "analyze_traffic_mirroring_logs"],
                    expected_criteria={"completeness": 4.0},
                    description="Basic performance analysis query"
                ),
                TestCase(
                    id="performance_retransmission_1",
                    query="I'm seeing high TCP retransmissions. Can you help identify the cause?",
                    category="retransmission_analysis",
                    expected_tools=["fix_retransmissions"],
                    expected_criteria={"accuracy": 4.0},
                    description="TCP retransmission analysis"
                )
            ])
        elif agent_type == "collaborator":
            scenarios.extend([
                TestCase(
                    id="collaborator_routing_1",
                    query="Route this network issue to the appropriate specialist agent",
                    category="agent_routing",
                    expected_tools=["send_message_tool"],
                    expected_criteria={"helpfulness": 4.0},
                    description="Agent-to-agent routing test"
                )
            ])
        
        return scenarios
    
    def _create_workflow_error(self, agent_name: str, error: str) -> Dict:
        """Create error result for workflow testing"""
        return {
            'agent_name': agent_name,
            'total_tests': 0,
            'passed_tests': 0,
            'success_rate': 0,
            'test_results': [],
            'workflow_status': 'failed',
            'error': error
        }
    
    async def _test_safety_features(self, config: Dict) -> Dict:
        """Test safety features specific to TroubleshootingAgent"""
        # TODO: Implement actual safety feature testing
        logger.warning("Safety feature testing not yet implemented")
        return {
            'test_status': 'not_implemented',
            'message': 'Safety feature testing requires implementation'
        }
    
    async def _test_performance_analysis(self, config: Dict) -> Dict:
        """Test performance analysis capabilities of PerformanceAgent"""
        # TODO: Implement actual performance analysis testing
        logger.warning("Performance analysis testing not yet implemented")
        return {
            'test_status': 'not_implemented',
            'message': 'Performance analysis testing requires implementation'
        }
    
    async def _test_a2a_communication(self, config: Dict) -> Dict:
        """Test A2A communication capabilities of CollaboratorAgent"""
        # TODO: Implement actual A2A communication testing
        logger.warning("A2A communication testing not yet implemented")
        return {
            'test_status': 'not_implemented', 
            'message': 'A2A communication testing requires implementation'
        }
    
    async def _run_llm_judge_evaluation(self, agent_name: str, initialization_results: Dict, 
                                      workflow_results: Dict, specific_results: Dict) -> Dict:
        """Run LLM-as-a-Judge evaluation on agent performance results"""
        try:
            # Check if we have actual workflow results to evaluate
            workflow_test_results = workflow_results.get('test_results', [])
            
            if not workflow_test_results:
                logger.warning(f"No workflow test results available for LLM judge evaluation of {agent_name}")
                return {
                    'judge_evaluations': [],
                    'aggregate_scores': {},
                    'overall_score': 0.0,
                    'samples_evaluated': 0,
                    'message': 'No test results available for evaluation',
                    'evaluation_timestamp': datetime.utcnow().isoformat()
                }
            
            # Evaluate actual test results using LLM judge
            judge_evaluations = []
            logger.info(f"=== Starting LLM Judge Evaluation for {agent_name} ===")
            logger.info(f"Total test results to evaluate: {len(workflow_test_results)}")
            
            for i, test_result in enumerate(workflow_test_results, 1):  # Evaluate ALL test results
                test_case_id = test_result.get('test_case_id', f'test_{i}')
                
                if 'error' not in test_result and test_result.get('response'):
                    try:
                        logger.info(f"📋 Evaluating Test {i}/{len(workflow_test_results)}: {test_case_id}")
                        logger.info(f"   Query: \"{test_result.get('query', 'N/A')[:100]}{'...' if len(test_result.get('query', '')) > 100 else ''}\"")
                        logger.info(f"   Response Time: {test_result.get('response_time', 0):.2f}s")
                        logger.info(f"   Response Length: {len(test_result.get('response', ''))} characters")
                        logger.info(f"   Detected Tools: {[tool.get('toolName', 'unknown') for tool in test_result.get('detected_tools', [])]}")
                        
                        evaluation = await self.llm_judge.evaluate_response(test_result)
                        judge_evaluations.append(evaluation)
                        
                        # Log detailed evaluation results
                        overall_score = evaluation.get('overall_score', 0)
                        scores = evaluation.get('scores', {})
                        
                        logger.info(f"   ✅ Evaluation Complete - Overall Score: {overall_score:.2f}/5.0")
                        for dimension, score_info in scores.items():
                            if isinstance(score_info, dict) and 'score' in score_info:
                                score = score_info['score']
                                logger.info(f"      • {dimension.capitalize()}: {score:.1f}/5.0")
                        
                        logger.info(f"   Tool Usage Score: {evaluation.get('tool_usage_score', 0):.2f}/5.0")
                        logger.info("")  # Empty line for readability
                        
                    except Exception as e:
                        logger.error(f"❌ Failed to evaluate test {test_case_id}: {e}")
                        logger.warning(f"   Skipping evaluation for test case: {test_case_id}")
                else:
                    logger.warning(f"⚠️  Skipping Test {i}: {test_case_id} - {'Has errors' if 'error' in test_result else 'No response'}")
                    if 'error' in test_result:
                        logger.warning(f"   Error: {test_result.get('error', 'Unknown error')}")
            
            logger.info(f"=== LLM Judge Evaluation Complete for {agent_name} ===")
            logger.info(f"Successfully evaluated {len(judge_evaluations)}/{len(workflow_test_results)} tests")
            
            if not judge_evaluations:
                return {
                    'judge_evaluations': [],
                    'aggregate_scores': {},
                    'overall_score': 0.0,
                    'samples_evaluated': 0,
                    'message': 'No successful evaluations completed',
                    'evaluation_timestamp': datetime.utcnow().isoformat()
                }
            
            # Calculate aggregate scores from actual evaluations
            dimensions = ['helpfulness', 'accuracy', 'clarity', 'professionalism', 'completeness']
            aggregate_scores = {}
            
            for dimension in dimensions:
                dimension_scores = []
                for eval_result in judge_evaluations:
                    scores = eval_result.get('scores', {})
                    if dimension in scores and isinstance(scores[dimension], dict):
                        dimension_scores.append(scores[dimension].get('score', 0))
                
                if dimension_scores:
                    avg_score = np.mean(dimension_scores)
                    aggregate_scores[dimension] = {
                        'score': avg_score,
                        'explanation': f"Average {dimension} score from {len(dimension_scores)} evaluations"
                    }
                else:
                    aggregate_scores[dimension] = {
                        'score': 0.0,
                        'explanation': f"No valid {dimension} scores found"
                    }
            
            # Calculate overall score from aggregates
            valid_scores = [scores['score'] for scores in aggregate_scores.values() if scores['score'] > 0]
            overall_score = np.mean(valid_scores) if valid_scores else 0.0
            
            return {
                'judge_evaluations': judge_evaluations,
                'aggregate_scores': aggregate_scores,
                'overall_score': overall_score,
                'samples_evaluated': len(judge_evaluations),
                'evaluation_timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"LLM Judge evaluation failed for {agent_name}: {e}")
            return {
                'judge_evaluations': [],
                'aggregate_scores': {},
                'overall_score': 0.0,
                'samples_evaluated': 0,
                'error': str(e),
                'evaluation_timestamp': datetime.utcnow().isoformat()
            }
    
    def _generate_comprehensive_report(self, evaluation_results: Dict) -> Dict:
        """Generate comprehensive evaluation report"""
        try:
            # Calculate summary statistics
            total_agents = len(evaluation_results)
            successful_evaluations = sum(1 for result in evaluation_results.values() 
                                       if 'error' not in result)
            
            # Generate report summary
            summary = {
                'evaluation_timestamp': datetime.utcnow().isoformat(),
                'total_agents_evaluated': total_agents,
                'successful_evaluations': successful_evaluations,
                'evaluation_success_rate': (successful_evaluations / total_agents * 100) if total_agents > 0 else 0,
                'agents_evaluated': list(evaluation_results.keys())
            }
            
            return {
                'summary': summary,
                'detailed_results': evaluation_results,
                'report_generated': True,
                'report_timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            return {
                'summary': {'error': str(e)},
                'detailed_results': evaluation_results,
                'report_generated': False,
                'report_timestamp': datetime.utcnow().isoformat()
            }


# Main execution function
async def main():
    """Main execution function for running agent evaluations"""
    try:
        pipeline = AgentEvaluationPipeline()
        results = await pipeline.run_comprehensive_evaluation()
        
        logger.info("Evaluation completed successfully")
        logger.info(f"Results: {json.dumps(results, indent=2, default=str)}")
        
        return results
        
    except Exception as e:
        logger.error(f"Evaluation pipeline failed: {e}")
        return {'error': str(e)}


if __name__ == "__main__":
    # Run the evaluation pipeline
    results = asyncio.run(main())
    print(json.dumps(results, indent=2, default=str))
