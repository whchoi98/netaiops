# NetAIOps - Network AI Operations Platform

AWS Bedrock AgentCore 기반의 지능형 네트워크 트러블슈팅 및 모니터링 플랫폼입니다.

## 개요

NetAIOps는 AI 에이전트를 활용하여 네트워크 문제를 자동으로 진단하고 해결하는 플랫폼입니다. AWS Bedrock AgentCore와 Claude Opus 4.5 모델을 기반으로 구축되었으며, 메모리 강화 에이전트, Agent-to-Agent(A2A) 협업, LLM-as-a-Judge 평가 프레임워크를 포함합니다.

## 주요 기능

| 기능 | 설명 |
|------|------|
| **자동화된 트러블슈팅** | DNS 분석, 연결성 진단, 네트워크 문제 자동 해결 |
| **성능 모니터링** | 네트워크 플로우 분석, PCAP 처리, 메트릭 추출 |
| **메모리 강화 에이전트** | Semantic, Summary, User Preference 메모리 전략 |
| **A2A 협업** | 멀티 에이전트 협업을 통한 복잡한 문제 해결 |
| **LLM-as-a-Judge** | Claude를 활용한 에이전트 응답 품질 자동 평가 |
| **안전성 검증** | 사용자 동의 기반의 안전한 인프라 수정 |

## 아키텍처

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         사용자 인터페이스                                 │
│                    (CLI / API / HTML Dashboard)                         │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
┌───────────────────────────────┴─────────────────────────────────────────┐
│                    AWS Bedrock AgentCore Runtime                         │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────┐  │
│  │ Troubleshooting │  │  Performance    │  │    Collaborator         │  │
│  │     Agent       │  │     Agent       │  │       Agent             │  │
│  │  (연결성 진단)   │  │  (성능 분석)    │  │  (에이전트 간 협업)      │  │
│  └────────┬────────┘  └────────┬────────┘  └───────────┬─────────────┘  │
│           │                    │                       │                │
│  ┌────────┴────────────────────┴───────────────────────┴─────────────┐  │
│  │                      Memory Management                             │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │  │
│  │  │   Semantic   │  │   Summary    │  │    User Preference       │ │  │
│  │  │   Memory     │  │   Memory     │  │       Memory             │ │  │
│  │  │ (장기 지식)   │  │ (세션 컨텍스트)│  │   (사용자 선호도)        │ │  │
│  │  └──────────────┘  └──────────────┘  └──────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
┌───────────────────────────────┴─────────────────────────────────────────┐
│                        진단 및 복구 도구 (Lambda)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐  │
│  │  DNS Lookup  │  │ Connectivity │  │  CloudWatch  │  │   Network   │  │
│  │              │  │    Check     │  │  Monitoring  │  │  Flow Log   │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └─────────────┘  │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
┌───────────────────────────────┴─────────────────────────────────────────┐
│                         AWS 인프라 레이어                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │  App VPC │  │Reporting │  │   RDS    │  │    S3    │  │CloudWatch│  │
│  │          │  │   VPC    │  │          │  │          │  │   Logs   │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## 프로젝트 구조

```
netaiops_v1/
├── README.md                    # 프로젝트 전체 문서 (현재 파일)
├── .gitignore                   # Git 제외 파일 목록
│
├── cfn_stack/                   # CloudFormation 인프라 템플릿
│   ├── README.md                # CFN 스택 문서
│   ├── deploy.sh                # 배포 스크립트
│   ├── sample-appication.yaml   # 1단계: 기본 인프라
│   ├── network-flow-monitor-enable.yaml    # 2a단계: NFM 활성화
│   ├── a2a-performance-agentcore-cognito.yaml  # 2b단계: Cognito
│   ├── module3-combined-setup.yaml         # 2c단계: 모듈 설치
│   ├── network-flow-monitor-setup.yaml     # 3단계: NFM 설정
│   └── trffice-mirroring-setup.yaml        # 4단계: 트래픽 미러링
│
├── workshop-module-1/           # 기본 AgentCore 설정
│   └── agentcore-reference/
│       ├── main.py              # 에이전트 엔트리포인트
│       ├── agent_config/        # 에이전트 설정
│       ├── Dockerfile           # 컨테이너 이미지
│       └── requirements.txt     # Python 의존성
│
├── workshop-module-2/           # 메모리 강화 에이전트
│   └── agentcore-reference/
│       ├── main.py
│       ├── agent_config/
│       │   ├── agent.py         # TroubleshootingAgent 구현
│       │   ├── memory_hook_provider.py  # 메모리 훅 구현
│       │   └── agent_task.py    # 태스크 래퍼
│       └── memory-strategies/   # 메모리 전략 문서
│
├── workshop-module-3/           # A2A 및 성능 에이전트
│   └── module-3/
│       ├── agentcore-connectivity-agent/   # 연결성 에이전트
│       ├── agentcore-performance-agent/    # 성능 에이전트
│       └── a2a/
│           └── a2a-collaborator-agent/     # 협업 에이전트
│
├── workshop-module-4/           # 고급 평가 프레임워크
│   ├── configs/
│   │   └── evaluation_config.yaml
│   ├── src/evaluation/
│   └── scripts/
│
└── module-4/                    # 평가 파이프라인 (독립 모듈)
    ├── README.md
    ├── configs/
    │   ├── evaluation_config.yaml
    │   └── test_scenarios/
    ├── src/evaluation/
    │   ├── agent_evaluation_pipeline.py
    │   ├── agentcore_client.py
    │   ├── aws_runtime_discovery.py
    │   └── config_loader.py
    └── scripts/
        ├── run_evaluation.sh
        ├── run_evaluation.py
        ├── generate_html_report.py
        └── setup_aws_prerequisites.sh
```

## 빠른 시작

### 사전 요구사항

- AWS 계정 및 적절한 IAM 권한
- AWS CLI 설치 및 구성
- Python 3.11+
- Docker (에이전트 배포용)

### 1단계: 인프라 배포

```bash
cd cfn_stack

# 전체 인프라 배포
./deploy.sh deploy-all

# 또는 개별 배포
./deploy.sh deploy-base        # 기본 인프라
./deploy.sh deploy-nfm         # Network Flow Monitor
./deploy.sh deploy-cognito     # Cognito 인증
```

### 2단계: 에이전트 설정

```bash
cd workshop-module-2/agentcore-reference

# 가상환경 생성 및 의존성 설치
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 에이전트 실행 (로컬 테스트)
python main.py
```

### 3단계: 에이전트 배포

```bash
# Bedrock AgentCore에 배포
bedrock-agentcore deploy
```

### 4단계: 평가 실행

```bash
cd module-4

# AWS 사전 요구사항 설정
./scripts/setup_aws_prerequisites.sh

# 평가 실행
./scripts/run_evaluation.sh

# HTML 리포트 생성
python scripts/generate_html_report.py --latest --open
```

## 모듈별 상세 설명

### Workshop Module 1: 기본 AgentCore 설정

기본적인 Bedrock AgentCore 에이전트 구조를 제공합니다.

**주요 구성요소:**
- `main.py`: AgentCore 앱 엔트리포인트
- `agent_config/agent.py`: 기본 에이전트 클래스
- `.bedrock_agentcore.yaml`: AgentCore 런타임 설정

### Workshop Module 2: 메모리 강화 에이전트

세 가지 메모리 전략을 통해 에이전트의 문맥 이해력을 향상시킵니다.

**메모리 전략:**

| 전략 | 설명 | 보존 기간 |
|------|------|-----------|
| **Semantic Memory** | 플랫폼 지식, 기술 문서 | 365일 |
| **Summary Memory** | 세션별 인시던트 컨텍스트 | 세션 기반 |
| **User Preference** | 사용자 선호도, SOP 절차 | 90일 |

### Workshop Module 3: A2A 협업

복잡한 문제를 해결하기 위한 멀티 에이전트 협업 패턴입니다.

**에이전트 역할:**

```
┌─────────────────────────────────────────────────────────┐
│              Collaborator Agent (라우터)                 │
│                    ↓           ↓                        │
│    ┌─────────────────┐    ┌─────────────────┐          │
│    │ Troubleshooting │    │   Performance   │          │
│    │     Agent       │    │     Agent       │          │
│    │  (연결성 진단)   │    │   (성능 분석)   │          │
│    └─────────────────┘    └─────────────────┘          │
└─────────────────────────────────────────────────────────┘
```

### Module 4: 평가 프레임워크

LLM-as-a-Judge 방식으로 에이전트 응답 품질을 자동 평가합니다.

**평가 차원:**

| 차원 | 가중치 | 설명 |
|------|--------|------|
| Helpfulness | 25% | 사용자 문제 해결에 대한 도움 정도 |
| Accuracy | 25% | 기술적 정확성 |
| Clarity | 20% | 명확성과 이해 용이성 |
| Professionalism | 15% | 전문성과 적절한 톤 |
| Completeness | 15% | 응답의 완전성 |

## 기술 스택

### AWS 서비스

| 서비스 | 용도 |
|--------|------|
| **Bedrock AgentCore** | AI 에이전트 런타임 |
| **Bedrock (Claude Opus 4.5)** | LLM 모델 |
| **Lambda** | 진단 도구 실행 |
| **CloudWatch** | 로그 및 메트릭 |
| **S3** | 결과 저장 |
| **Cognito** | 인증 |
| **VPC** | 네트워크 인프라 |
| **RDS** | 데이터베이스 |

### Python 라이브러리

```
strands-agents          # 에이전트 오케스트레이션
bedrock-agentcore       # AWS AgentCore 통합
boto3                   # AWS SDK
pydantic                # 데이터 검증
structlog               # 구조화된 로깅
matplotlib              # 차트 생성
jinja2                  # HTML 템플릿
```

## 설정

### 환경 변수

```bash
# AWS 설정
export AWS_REGION=us-east-1
export AWS_PROFILE=default

# 평가 설정
export LLM_JUDGE_MODEL_ID=global.anthropic.claude-opus-4-5-20251101-v1:0

# 선택적 설정
export CLOUDWATCH_LOG_GROUP=/aws/bedrock-agentcore/troubleshooting-agent
```

### 설정 파일

**evaluation_config.yaml:**
```yaml
aws:
  region: "us-east-1"
  account_id: "${AWS_ACCOUNT_ID}"

llm_judge:
  model_id: "${LLM_JUDGE_MODEL_ID:-global.anthropic.claude-opus-4-5-20251101-v1:0}"
  evaluation_dimensions:
    - helpfulness
    - accuracy
    - clarity
    - professionalism
    - completeness

scoring:
  passing_score_threshold: 3.5
  excellent_score_threshold: 4.5
```

## 테스트 시나리오

평가 프레임워크에 포함된 기본 테스트 시나리오:

| 카테고리 | 시나리오 | 설명 |
|----------|----------|------|
| **연결성** | DNS Resolution | DNS 조회 실패 진단 |
| | Connectivity Check | 네트워크 연결성 확인 |
| | Timeout Analysis | 타임아웃 문제 분석 |
| **성능** | Latency Analysis | 지연 시간 분석 |
| | Throughput Check | 처리량 확인 |
| | Flow Analysis | 네트워크 플로우 분석 |
| **안전성** | Consent Validation | 수정 작업 동의 확인 |
| | Read-Only Operations | 읽기 전용 작업 검증 |

## 문제 해결

### 일반적인 문제

| 문제 | 원인 | 해결 방법 |
|------|------|-----------|
| 에이전트 응답 없음 | 모델 접근 권한 없음 | Bedrock 모델 접근 권한 확인 |
| CloudWatch 로그 없음 | 로그 그룹 미생성 | 로그 그룹 생성 또는 이름 확인 |
| 메모리 저장 실패 | Memory API 권한 없음 | IAM 정책에 bedrock-agentcore:* 추가 |
| 평가 실패 | 런타임 미발견 | AgentCore 런타임 배포 상태 확인 |

### 로그 확인

```bash
# CloudWatch 로그 확인
aws logs tail /aws/bedrock-agentcore/troubleshooting-agent --follow

# 에이전트 상태 확인
bedrock-agentcore list-runtimes
```

## 기여 방법

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 관련 문서

- [AWS Bedrock AgentCore 문서](https://docs.aws.amazon.com/bedrock/)
- [Strands Agents 문서](https://github.com/strands-agents/strands-agents)
- [CloudFormation 문서](https://docs.aws.amazon.com/cloudformation/)

## 라이선스

이 프로젝트는 내부 워크샵 및 교육 목적으로 제작되었습니다.

## 연락처

- Repository: https://github.com/whchoi98/netaiops
- Issues: https://github.com/whchoi98/netaiops/issues
