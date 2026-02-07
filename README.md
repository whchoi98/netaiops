# NetAIOps - Network AI Operations Platform

AWS Bedrock AgentCore 기반의 지능형 네트워크 트러블슈팅 및 모니터링 플랫폼

---

## 목차

1. [개요](#개요)
2. [주요 기능](#주요-기능)
3. [아키텍처](#아키텍처)
4. [프로젝트 구조](#프로젝트-구조)
5. [빠른 시작](#빠른-시작)
6. [배포 스크립트](#배포-스크립트)
7. [모듈별 설명](#모듈별-설명)
8. [설정](#설정)
9. [문제 해결](#문제-해결)
10. [변경 이력](#변경-이력)

---

## 개요

NetAIOps는 AI 에이전트를 활용하여 네트워크 문제를 자동으로 진단하고 해결하는 플랫폼입니다.

**핵심 구성 요소:**
- AWS Bedrock AgentCore 런타임
- Claude 모델 (Opus 4.5 / Sonnet 4 선택 가능)
- 메모리 강화 에이전트
- Agent-to-Agent(A2A) 협업 프레임워크
- LLM-as-a-Judge 평가 시스템

**문서 특징:**
- 모든 소스 코드에 영어/한글 이중 언어 주석 포함
- All source code includes bilingual (English/Korean) comments

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| 자동화된 트러블슈팅 | DNS 분석, 연결성 진단, 네트워크 문제 자동 해결 |
| 성능 모니터링 | 네트워크 플로우 분석, PCAP 처리, 메트릭 추출 |
| 메모리 강화 에이전트 | Semantic, Summary, User Preference 메모리 전략 |
| A2A 협업 | 멀티 에이전트 협업을 통한 복잡한 문제 해결 |
| LLM-as-a-Judge | Claude를 활용한 에이전트 응답 품질 자동 평가 |
| 안전성 검증 | 사용자 동의 기반의 안전한 인프라 수정 |

---

## 아키텍처

```
+-------------------------------------------------------------------------+
|                         사용자 인터페이스                                 |
|                    (CLI / API / HTML Dashboard)                         |
+------------------------------------+------------------------------------+
                                     |
+------------------------------------v------------------------------------+
|                    AWS Bedrock AgentCore Runtime                        |
|  +------------------+  +------------------+  +------------------------+  |
|  | Troubleshooting  |  |   Performance    |  |     Collaborator       |  |
|  |      Agent       |  |      Agent       |  |        Agent           |  |
|  |   (연결성 진단)   |  |    (성능 분석)   |  |   (에이전트 간 협업)    |  |
|  +--------+---------+  +--------+---------+  +-----------+------------+  |
|           |                     |                        |               |
|  +--------+---------------------+------------------------+-----------+   |
|  |                       Memory Management                           |   |
|  |  +--------------+  +--------------+  +-------------------------+  |   |
|  |  |   Semantic   |  |   Summary    |  |     User Preference     |  |   |
|  |  |    Memory    |  |    Memory    |  |         Memory          |  |   |
|  |  |  (장기 지식)  |  |(세션 컨텍스트)|  |     (사용자 선호도)      |  |   |
|  |  +--------------+  +--------------+  +-------------------------+  |   |
|  +-------------------------------------------------------------------+   |
+------------------------------------+------------------------------------+
                                     |
+------------------------------------v------------------------------------+
|                       진단 및 복구 도구 (Lambda)                         |
|  +--------------+  +--------------+  +--------------+  +--------------+  |
|  |  DNS Lookup  |  | Connectivity |  |  CloudWatch  |  |   Network    |  |
|  |              |  |    Check     |  |  Monitoring  |  |  Flow Log    |  |
|  +--------------+  +--------------+  +--------------+  +--------------+  |
+------------------------------------+------------------------------------+
                                     |
+------------------------------------v------------------------------------+
|                          AWS 인프라 레이어                               |
|  +----------+  +----------+  +----------+  +----------+  +----------+   |
|  |  App VPC |  | Reporting|  |   RDS    |  |    S3    |  |CloudWatch|   |
|  |          |  |   VPC    |  |          |  |          |  |   Logs   |   |
|  +----------+  +----------+  +----------+  +----------+  +----------+   |
+-------------------------------------------------------------------------+
```

---

## 프로젝트 구조

```
netaiops_v1/
├── README.md                           # 프로젝트 문서 (현재 파일)
├── .gitignore                          # Git 제외 파일 목록
│
├── cfn_stack/                          # CloudFormation 인프라 템플릿
│   ├── deploy.sh                       # 배포 스크립트 (리전/모델 선택 지원)
│   ├── .deploy-config                  # 저장된 설정 (자동 생성)
│   ├── sample-appication.yaml          # Stage 1: 기본 인프라
│   ├── network-flow-monitor-enable.yaml # Stage 2a: NFM 활성화
│   ├── a2a-performance-agentcore-cognito.yaml # Stage 2b: Cognito
│   ├── module3-combined-setup.yaml     # Stage 2c: 모듈 설치
│   ├── network-flow-monitor-setup.yaml # Stage 3: NFM 설정
│   └── trffice-mirroring-setup.yaml    # Stage 4: 트래픽 미러링
│
├── workshop-module-1/                  # Module 1: 기본 AgentCore 설정
│   └── agentcore-reference/
│       ├── main.py                     # 에이전트 엔트리포인트
│       ├── agent_config/agent.py       # TroubleshootingAgent 클래스
│       └── requirements.txt            # Python 의존성
│
├── workshop-module-2/                  # Module 2: 메모리 강화 에이전트
│   └── agentcore-reference/
│       └── agent_config/
│           ├── agent.py                # 메모리 강화 에이전트
│           └── memory_hook_provider.py # 3계층 메모리 훅
│
├── workshop-module-3/                  # Module 3: A2A 협업
│   └── module-3/
│       ├── agentcore-connectivity-agent/  # 연결성 에이전트
│       ├── agentcore-performance-agent/   # 성능 에이전트
│       └── a2a/a2a-collaborator-agent/    # 협업 오케스트레이터
│
├── workshop-module-4/                  # Module 4: 평가 프레임워크
│   ├── configs/evaluation_config.yaml
│   └── src/evaluation/
│
└── module-4/                           # 평가 파이프라인 (독립 모듈)
    ├── configs/evaluation_config.yaml
    └── src/evaluation/
        ├── agent_evaluation_pipeline.py # LLM-as-a-Judge 평가
        └── agentcore_client.py         # AgentCore 클라이언트
```

---

## 빠른 시작

### 사전 요구사항

- AWS 계정 및 IAM 권한
- AWS CLI 설치 및 구성
- Python 3.11+
- Docker (에이전트 배포용)

### Step 1: 인프라 배포

```bash
cd cfn_stack

# 전체 배포 (대화형 리전/모델 선택)
./deploy.sh deploy-all

# 또는 명시적 지정
./deploy.sh deploy-all --region us-east-1 --model opus-4.5
```

### Step 2: 에이전트 설정

```bash
cd workshop-module-2/agentcore-reference

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python main.py  # 로컬 테스트
```

### Step 3: 에이전트 배포

```bash
bedrock-agentcore deploy
```

### Step 4: 평가 실행

```bash
cd module-4
./scripts/setup_aws_prerequisites.sh
./scripts/run_evaluation.sh
python scripts/generate_html_report.py --latest --open
```

---

## 배포 스크립트

### 지원 리전

| 리전 | 설명 |
|------|------|
| us-east-1 | 기본값, 권장 |
| us-west-2 | 미국 서부 |
| eu-west-1 | 유럽 |
| ap-northeast-1 | 도쿄 |
| ap-southeast-1 | 싱가포르 |

### 지원 모델

| 모델명 | 모델 ID | 특성 |
|--------|---------|------|
| opus-4.6 | global.anthropic.claude-opus-4-6-v1 | 최신 최고 성능 (기본값) |
| opus-4.5 | global.anthropic.claude-opus-4-5-20251101-v1:0 | 고성능 |
| sonnet-4 | global.anthropic.claude-sonnet-4-20250514-v1:0 | 빠른 응답, 비용 효율 |

### 명령어 레퍼런스

**배포 명령:**
```bash
./deploy.sh deploy-all          # 전체 스택 배포 (권장)
./deploy.sh deploy-base         # 기본 인프라만
./deploy.sh deploy-nfm          # Network Flow Monitor (enable + setup)
./deploy.sh deploy-cognito      # Cognito 인증
./deploy.sh deploy-modules      # 모듈 설치
./deploy.sh deploy-traffic      # Traffic Mirroring
```

### 배포 순서

**deploy-all 실행 순서 (권장):**
```
[0/5] S3 버킷 준비
[1/5] sample-app (기본 인프라)
[2/5] nfm-enable (NFM 활성화)
[3/5] cognito + modules (인증 및 모듈)
[4/5] nfm-setup (NFM 설정)
[5/5] traffic-mirror (트래픽 미러링)
[정리] S3 템플릿 삭제
```

**개별 명령 순차 실행 시:**
```
deploy-base    → sample-app
deploy-nfm     → nfm-enable + nfm-setup (한번에 실행)
deploy-cognito → cognito
deploy-modules → modules
deploy-traffic → traffic-mirror
```

**deploy-all vs 개별 명령 차이점:**

| 항목 | deploy-all | 개별 명령 순차 실행 |
|------|-----------|-------------------|
| NFM 배포 | Enable → (다른 작업) → Setup 분리 | Enable + Setup 한번에 |
| S3 정리 | 완료 후 자동 정리 | 수동 cleanup-templates 필요 |
| 상태 표시 | 완료 후 자동 표시 | 수동 status 실행 필요 |
| 진행 상황 | 단계별 표시 | 개별 표시 |

> 참고: 개별 명령도 의존성이 충족되면 정상 작동하지만, `deploy-all`이 최적화된 순서로 배포합니다.

### 실시간 진행 상황 표시

배포 중 CloudFormation 리소스 생성 이벤트가 실시간으로 표시됩니다:

```
[STEP] 배포 중: netaiops-sample-app

[INFO] 리소스 생성 진행 상황:
────────────────────────────────────────────────────────────────────
시간                      리소스                              상태
────────────────────────────────────────────────────────────────────
14:32:15                 AppVPC                              CREATE_IN_PROGRESS
14:32:18                 AppVPC                              CREATE_COMPLETE
14:32:20                 PublicSubnet1                       CREATE_IN_PROGRESS
...
────────────────────────────────────────────────────────────────────

[SUCCESS] netaiops-sample-app 배포 완료
```

**상태 색상:**
- 녹색: 완료 (CREATE_COMPLETE, UPDATE_COMPLETE)
- 노란색: 진행 중 (CREATE_IN_PROGRESS)
- 빨간색: 실패 (CREATE_FAILED, ROLLBACK)

**삭제 명령:**
```bash
./deploy.sh delete-all          # 전체 삭제 (역순)
./deploy.sh delete [stack]      # 특정 스택 삭제
./deploy.sh delete-bucket       # S3 버킷 삭제
```

**설정 명령:**
```bash
./deploy.sh show-config         # 전체 설정 확인
./deploy.sh set-region          # 리전 변경
./deploy.sh set-model           # 모델 변경
./deploy.sh show-region         # 현재 리전 확인
./deploy.sh show-model          # 현재 모델 확인
./deploy.sh status              # 스택 상태 확인
```

**옵션:**
```bash
--region REGION     # AWS 리전 (us-east-1, ap-northeast-1 등)
--model MODEL       # Claude 모델 (opus-4.6 | opus-4.5 | sonnet-4)
--db-password PWD   # 데이터베이스 비밀번호
```

### 설정 우선순위

| 순위 | 소스 | 예시 |
|------|------|------|
| 1 | 명령줄 옵션 | --region us-east-1 --model opus-4.5 |
| 2 | 환경변수 | AWS_REGION, BEDROCK_MODEL_ID |
| 3 | 설정 파일 | .deploy-config |
| 4 | 대화형 프롬프트 | 실행 시 선택 |

---

## 모듈별 설명

### Module 1: 기본 AgentCore 설정

기본적인 Bedrock AgentCore 에이전트 구조를 제공합니다.

**주요 파일:**
- main.py: AgentCore 앱 엔트리포인트
- agent_config/agent.py: TroubleshootingAgent 클래스
- .bedrock_agentcore.yaml: AgentCore 런타임 설정

### Module 2: 메모리 강화 에이전트

3계층 메모리 시스템으로 에이전트의 문맥 이해력을 향상시킵니다.

| 메모리 유형 | 용도 | 보존 기간 |
|-------------|------|-----------|
| Semantic Memory | 플랫폼 지식, 기술 문서 | 365일 |
| Summary Memory | 세션별 분석 결과, PathID | 세션 기반 |
| User Preference | 사용자 선호도, SOP 절차 | 90일 |

### Module 3: A2A 협업

멀티 에이전트 협업 패턴을 구현합니다.

```
Collaborator Agent (오케스트레이터)
        |
   +----+----+
   |         |
   v         v
Connectivity  Performance
  Agent        Agent
```

**에이전트 역할:**
- Collaborator Agent: 요청 라우팅, 응답 집계
- Connectivity Agent: DNS 해석, 연결성 분석
- Performance Agent: PCAP 분석, 지연 측정

### Module 4: 평가 프레임워크

LLM-as-a-Judge 방식의 자동 품질 평가 시스템입니다.

**평가 차원:**

| 차원 | 가중치 | 설명 |
|------|--------|------|
| Helpfulness | 25% | 문제 해결 도움 정도 |
| Accuracy | 25% | 기술적 정확성 |
| Clarity | 20% | 명확성과 이해 용이성 |
| Professionalism | 15% | 전문성과 적절한 톤 |
| Completeness | 15% | 응답의 완전성 |

---

## 설정

### 환경 변수

```bash
# AWS 설정
export AWS_REGION=us-east-1
export AWS_PROFILE=default

# 모델 설정 (모든 에이전트에 적용)
export BEDROCK_MODEL_ID=global.anthropic.claude-opus-4-5-20251101-v1:0
```

### 설정 파일

**cfn_stack/.deploy-config** (자동 생성):
```bash
AWS_REGION="us-east-1"
BEDROCK_MODEL_ID="global.anthropic.claude-opus-4-5-20251101-v1:0"
```

**evaluation_config.yaml:**
```yaml
aws:
  region: "us-east-1"
  account_id: "${AWS_ACCOUNT_ID}"

llm_judge:
  model_id: "${BEDROCK_MODEL_ID:-global.anthropic.claude-opus-4-5-20251101-v1:0}"
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

---

## 문제 해결

### 일반적인 문제

| 증상 | 원인 | 해결 방법 |
|------|------|-----------|
| 에이전트 응답 없음 | 모델 접근 권한 없음 | Bedrock 콘솔에서 모델 접근 권한 확인 |
| CloudWatch 로그 없음 | 로그 그룹 미생성 | 로그 그룹 생성 또는 이름 확인 |
| 메모리 저장 실패 | Memory API 권한 없음 | IAM 정책에 bedrock-agentcore:* 추가 |
| 평가 실패 | 런타임 미발견 | AgentCore 런타임 배포 상태 확인 |

### 로그 확인

```bash
# CloudWatch 로그 실시간 확인
aws logs tail /aws/bedrock-agentcore/troubleshooting-agent --follow

# 에이전트 상태 확인
bedrock-agentcore list-runtimes

# 스택 상태 확인
./deploy.sh status
```

---

## 변경 이력

### v1.1.0 (2026-02-05)

**신규 기능:**
- 대화형 리전 선택 (Bedrock AgentCore 지원 리전)
- 대화형 모델 선택 (Opus 4.5 / Sonnet 4)
- 설정 저장 기능 (.deploy-config)
- set-region, show-region, set-model, show-model, show-config 명령어

**코드 품질 개선:**
- 모든 코드에 영어/한글 이중 언어 주석 추가
- 모듈별 상세 docstring 추가
- 환경변수 BEDROCK_MODEL_ID로 통일

**변경 파일:**
- cfn_stack/deploy.sh
- workshop-module-1/2/3 에이전트 파일들
- module-4, workshop-module-4 평가 파이프라인

### v1.0.0 (2026-01-18)

**초기 릴리스:**
- 기본 AgentCore 에이전트 (Module 1)
- 메모리 강화 에이전트 (Module 2)
- A2A 협업 프레임워크 (Module 3)
- LLM-as-a-Judge 평가 프레임워크 (Module 4)
- CloudFormation 인프라 템플릿

---

## 참고 문서

- [AWS Bedrock AgentCore](https://docs.aws.amazon.com/bedrock/)
- [Strands Agents](https://github.com/strands-agents/strands-agents)
- [AWS CloudFormation](https://docs.aws.amazon.com/cloudformation/)

---

## 라이선스

이 프로젝트는 내부 워크샵 및 교육 목적으로 제작되었습니다.

## 연락처

- Repository: https://github.com/whchoi98/netaiops
- Issues: https://github.com/whchoi98/netaiops/issues
