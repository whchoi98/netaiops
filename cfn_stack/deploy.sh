#!/bin/bash
#
# NetAIOps CloudFormation 스택 배포 스크립트
# S3 버킷을 사용하여 대용량 템플릿을 배포합니다.
# 사용법: ./deploy.sh [command] [options]
#

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 기본 설정
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID=""
S3_BUCKET_NAME=""
S3_PREFIX="netaiops-cfn-templates"

# 스택 이름 설정
STACK_SAMPLE_APP="netaiops-sample-app"
STACK_NFM_ENABLE="netaiops-nfm-enable"
STACK_NFM_SETUP="netaiops-nfm-setup"
STACK_COGNITO="netaiops-cognito"
STACK_MODULES="netaiops-modules"
STACK_TRAFFIC_MIRROR="netaiops-traffic-mirror"

# 함수: 로그 출력
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${CYAN}[STEP]${NC} $1"; }

# 함수: AWS 계정 ID 가져오기
get_aws_account_id() {
    if [ -z "$AWS_ACCOUNT_ID" ]; then
        AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)
        if [ -z "$AWS_ACCOUNT_ID" ]; then
            log_error "AWS 계정 ID를 가져올 수 없습니다. AWS 자격 증명을 확인하세요."
            exit 1
        fi
    fi
    echo "$AWS_ACCOUNT_ID"
}

# 함수: S3 버킷 이름 생성/확인
get_s3_bucket_name() {
    if [ -z "$S3_BUCKET_NAME" ]; then
        local account_id=$(get_aws_account_id)
        S3_BUCKET_NAME="netaiops-cfn-${account_id}-${AWS_REGION}"
    fi
    echo "$S3_BUCKET_NAME"
}

# 함수: S3 버킷 생성 (없는 경우)
ensure_s3_bucket() {
    local bucket_name=$(get_s3_bucket_name)

    log_info "S3 버킷 확인 중: $bucket_name"

    # 버킷 존재 여부 확인
    if aws s3api head-bucket --bucket "$bucket_name" 2>/dev/null; then
        log_info "S3 버킷이 이미 존재합니다: $bucket_name"
    else
        log_info "S3 버킷 생성 중: $bucket_name"

        # us-east-1은 LocationConstraint를 지정하지 않음
        if [ "$AWS_REGION" = "us-east-1" ]; then
            aws s3api create-bucket \
                --bucket "$bucket_name" \
                --region "$AWS_REGION" \
                > /dev/null
        else
            aws s3api create-bucket \
                --bucket "$bucket_name" \
                --region "$AWS_REGION" \
                --create-bucket-configuration LocationConstraint="$AWS_REGION" \
                > /dev/null
        fi

        # 버킷 버전 관리 활성화
        aws s3api put-bucket-versioning \
            --bucket "$bucket_name" \
            --versioning-configuration Status=Enabled \
            > /dev/null

        # 퍼블릭 액세스 차단
        aws s3api put-public-access-block \
            --bucket "$bucket_name" \
            --public-access-block-configuration \
            "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" \
            > /dev/null

        log_success "S3 버킷 생성 완료: $bucket_name"
    fi
}

# 함수: 템플릿을 S3에 업로드
upload_template_to_s3() {
    local template_file=$1
    local bucket_name=$(get_s3_bucket_name)
    local s3_key="${S3_PREFIX}/$(basename $template_file)"

    log_info "템플릿 업로드 중: $(basename $template_file) -> s3://${bucket_name}/${s3_key}"

    aws s3 cp "${SCRIPT_DIR}/${template_file}" "s3://${bucket_name}/${s3_key}" \
        --region "$AWS_REGION" \
        > /dev/null

    echo "s3://${bucket_name}/${s3_key}"
}

# 함수: S3에서 CFN 템플릿 정리
cleanup_s3_templates() {
    local bucket_name=$(get_s3_bucket_name)

    log_info "S3 템플릿 정리 중: s3://${bucket_name}/${S3_PREFIX}/"

    # 버킷이 존재하는지 확인
    if aws s3api head-bucket --bucket "$bucket_name" 2>/dev/null; then
        # 템플릿 프리픽스 아래의 모든 객체 삭제
        aws s3 rm "s3://${bucket_name}/${S3_PREFIX}/" --recursive > /dev/null 2>&1 || true

        # 버전된 객체도 삭제 (버전 관리가 활성화된 경우)
        aws s3api list-object-versions --bucket "$bucket_name" --prefix "${S3_PREFIX}/" --output json 2>/dev/null | \
            jq -r '.Versions[]? | "\(.Key) \(.VersionId)"' 2>/dev/null | \
            while read key version; do
                [ -n "$key" ] && [ -n "$version" ] && \
                aws s3api delete-object --bucket "$bucket_name" --key "$key" --version-id "$version" > /dev/null 2>&1 || true
            done

        # 삭제 마커도 제거
        aws s3api list-object-versions --bucket "$bucket_name" --prefix "${S3_PREFIX}/" --output json 2>/dev/null | \
            jq -r '.DeleteMarkers[]? | "\(.Key) \(.VersionId)"' 2>/dev/null | \
            while read key version; do
                [ -n "$key" ] && [ -n "$version" ] && \
                aws s3api delete-object --bucket "$bucket_name" --key "$key" --version-id "$version" > /dev/null 2>&1 || true
            done

        log_success "S3 템플릿 정리 완료"
    else
        log_warn "S3 버킷이 존재하지 않습니다: $bucket_name"
    fi
}

# 함수: 스택 배포 (S3 사용)
deploy_stack() {
    local stack_name=$1
    local template_file=$2
    shift 2
    local params=("$@")

    log_step "배포 중: $stack_name"

    # S3 버킷 확인/생성
    ensure_s3_bucket

    local bucket_name=$(get_s3_bucket_name)

    # 템플릿을 S3에 업로드
    local s3_url=$(upload_template_to_s3 "$template_file")

    # CloudFormation 배포 명령 구성
    local cmd="aws cloudformation deploy \
        --template-file ${SCRIPT_DIR}/${template_file} \
        --stack-name ${stack_name} \
        --s3-bucket ${bucket_name} \
        --s3-prefix ${S3_PREFIX} \
        --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
        --region ${AWS_REGION}"

    if [ ${#params[@]} -gt 0 ]; then
        cmd+=" --parameter-overrides ${params[*]}"
    fi

    if eval $cmd; then
        log_success "$stack_name 배포 완료"
    else
        log_error "$stack_name 배포 실패"
        return 1
    fi
}

# 함수: 스택 상태 확인
check_stack_status() {
    local stack_name=$1
    aws cloudformation describe-stacks \
        --stack-name "$stack_name" \
        --region "$AWS_REGION" \
        --query 'Stacks[0].StackStatus' \
        --output text 2>/dev/null || echo "NOT_FOUND"
}

# 함수: 스택 삭제
delete_stack() {
    local stack_name=$1
    log_info "삭제 중: $stack_name"

    if aws cloudformation delete-stack --stack-name "$stack_name" --region "$AWS_REGION" 2>/dev/null; then
        log_info "삭제 대기 중: $stack_name"
        aws cloudformation wait stack-delete-complete --stack-name "$stack_name" --region "$AWS_REGION" 2>/dev/null || true
        log_success "$stack_name 삭제 완료"
    else
        log_warn "$stack_name 스택이 존재하지 않거나 이미 삭제됨"
    fi
}

# 함수: S3 버킷 삭제
delete_s3_bucket() {
    local bucket_name=$(get_s3_bucket_name)

    log_info "S3 버킷 삭제 중: $bucket_name"

    # 버킷이 존재하는지 확인
    if aws s3api head-bucket --bucket "$bucket_name" 2>/dev/null; then
        # 버킷 내 모든 객체 삭제 (버전 포함)
        aws s3 rm "s3://${bucket_name}" --recursive > /dev/null 2>&1 || true

        # 버전된 객체 삭제
        aws s3api list-object-versions --bucket "$bucket_name" --output json 2>/dev/null | \
            jq -r '.Versions[]? | "\(.Key) \(.VersionId)"' 2>/dev/null | \
            while read key version; do
                aws s3api delete-object --bucket "$bucket_name" --key "$key" --version-id "$version" > /dev/null 2>&1 || true
            done

        # 삭제 마커 제거
        aws s3api list-object-versions --bucket "$bucket_name" --output json 2>/dev/null | \
            jq -r '.DeleteMarkers[]? | "\(.Key) \(.VersionId)"' 2>/dev/null | \
            while read key version; do
                aws s3api delete-object --bucket "$bucket_name" --key "$key" --version-id "$version" > /dev/null 2>&1 || true
            done

        # 버킷 삭제
        aws s3api delete-bucket --bucket "$bucket_name" --region "$AWS_REGION" > /dev/null 2>&1 || true
        log_success "S3 버킷 삭제 완료: $bucket_name"
    else
        log_warn "S3 버킷이 존재하지 않습니다: $bucket_name"
    fi
}

# 함수: 사용법 출력
show_usage() {
    cat << EOF
NetAIOps CloudFormation 배포 스크립트 (S3 지원)

사용법: $0 [command] [options]

Commands:
  deploy-all          모든 스택 순차 배포
  deploy-base         기본 인프라만 배포 (sample-app)
  deploy-nfm          Network Flow Monitor 배포 (enable + setup)
  deploy-cognito      Cognito 인증 스택 배포
  deploy-modules      모듈 설치 스택 배포
  deploy-traffic      Traffic Mirroring 스택 배포

  delete-all          모든 스택 삭제 (역순)
  delete [stack]      특정 스택 삭제
  delete-bucket       CFN 템플릿용 S3 버킷 삭제
  cleanup-templates   S3의 CFN 템플릿만 삭제

  status              모든 스택 상태 확인
  list                배포된 스택 목록

  init                S3 버킷만 생성 (사전 준비)

Options:
  --region REGION     AWS 리전 (기본: us-east-1)
  --db-password PWD   DB 비밀번호 (기본: ReInvent2025!)
  --s3-bucket NAME    사용할 S3 버킷 이름 (기본: 자동 생성)
  -h, --help          도움말

Examples:
  $0 deploy-all
  $0 deploy-all --region ap-northeast-2
  $0 deploy-base --db-password MySecurePass123!
  $0 status
  $0 delete-all

S3 버킷:
  - 대용량 CloudFormation 템플릿(>51KB) 배포를 위해 S3 버킷을 자동 생성합니다.
  - 버킷 이름: netaiops-cfn-{AWS_ACCOUNT_ID}-{AWS_REGION}
  - 삭제 시 --delete-bucket 옵션으로 S3 버킷도 함께 삭제할 수 있습니다.

EOF
}

# 함수: 모든 스택 상태 확인
show_status() {
    log_info "스택 상태 확인 중..."
    echo ""
    printf "%-30s %-25s\n" "스택 이름" "상태"
    echo "--------------------------------------------------------"

    for stack in "$STACK_SAMPLE_APP" "$STACK_NFM_ENABLE" "$STACK_NFM_SETUP" \
                 "$STACK_COGNITO" "$STACK_MODULES" "$STACK_TRAFFIC_MIRROR"; do
        status=$(check_stack_status "$stack")
        printf "%-30s %-25s\n" "$stack" "$status"
    done

    echo ""
    local bucket_name=$(get_s3_bucket_name)
    if aws s3api head-bucket --bucket "$bucket_name" 2>/dev/null; then
        log_info "S3 버킷: $bucket_name (존재)"
    else
        log_info "S3 버킷: $bucket_name (없음)"
    fi
}

# 함수: 기본 인프라 배포
deploy_base() {
    local db_password="${1:-ReInvent2025!}"
    deploy_stack "$STACK_SAMPLE_APP" "sample-appication.yaml" \
        "DBPassword=$db_password"
}

# 함수: NFM 배포
deploy_nfm() {
    # 1. NFM Enable
    deploy_stack "$STACK_NFM_ENABLE" "network-flow-monitor-enable.yaml"

    # 2. NFM Setup
    deploy_stack "$STACK_NFM_SETUP" "network-flow-monitor-setup.yaml" \
        "SampleApplicationStackName=$STACK_SAMPLE_APP" \
        "NetworkFlowMonitorEnableStackName=$STACK_NFM_ENABLE"
}

# 함수: Cognito 배포
deploy_cognito() {
    deploy_stack "$STACK_COGNITO" "a2a-performance-agentcore-cognito.yaml"
}

# 함수: 모듈 배포
deploy_modules() {
    deploy_stack "$STACK_MODULES" "module3-combined-setup.yaml" \
        "SampleApplicationStackName=$STACK_SAMPLE_APP"
}

# 함수: Traffic Mirroring 배포
deploy_traffic() {
    deploy_stack "$STACK_TRAFFIC_MIRROR" "trffice-mirroring-setup.yaml" \
        "SampleApplicationStackName=$STACK_SAMPLE_APP" \
        "NetworkFlowMonitorStackName=$STACK_NFM_SETUP"
}

# 함수: 전체 배포
deploy_all() {
    local db_password="${1:-ReInvent2025!}"

    log_info "=== NetAIOps 전체 스택 배포 시작 ==="
    echo ""

    # S3 버킷 사전 생성
    log_step "[0/5] S3 버킷 준비"
    ensure_s3_bucket
    echo ""

    # 1단계: 기본 인프라
    log_step "[1/5] 기본 애플리케이션 인프라 배포"
    deploy_base "$db_password"
    echo ""

    # 2단계: NFM Enable
    log_step "[2/5] NFM Enable 배포"
    deploy_stack "$STACK_NFM_ENABLE" "network-flow-monitor-enable.yaml"
    echo ""

    # 3단계: Cognito 및 모듈 배포
    log_step "[3/5] Cognito 및 모듈 배포"
    deploy_cognito
    deploy_modules
    echo ""

    # 4단계: NFM Setup
    log_step "[4/5] NFM Setup 배포"
    deploy_stack "$STACK_NFM_SETUP" "network-flow-monitor-setup.yaml" \
        "SampleApplicationStackName=$STACK_SAMPLE_APP" \
        "NetworkFlowMonitorEnableStackName=$STACK_NFM_ENABLE"
    echo ""

    # 5단계: Traffic Mirroring
    log_step "[5/5] Traffic Mirroring 배포"
    deploy_traffic

    echo ""

    # 배포 완료 후 S3 템플릿 정리
    log_step "[정리] S3 템플릿 삭제"
    cleanup_s3_templates

    echo ""
    log_success "=== 전체 배포 완료 ==="
    echo ""
    show_status
}

# 함수: 전체 삭제 (역순)
delete_all() {
    local delete_bucket=false

    # 옵션 확인
    if [[ "$1" == "--delete-bucket" ]]; then
        delete_bucket=true
    fi

    log_info "=== NetAIOps 전체 스택 삭제 시작 ==="
    log_warn "모든 리소스가 삭제됩니다. 계속하시겠습니까? (y/N)"
    read -r confirm

    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        log_info "삭제 취소됨"
        return 0
    fi

    # 역순 삭제
    delete_stack "$STACK_TRAFFIC_MIRROR"
    delete_stack "$STACK_NFM_SETUP"
    delete_stack "$STACK_MODULES"
    delete_stack "$STACK_COGNITO"
    delete_stack "$STACK_NFM_ENABLE"
    delete_stack "$STACK_SAMPLE_APP"

    # S3 버킷 삭제 (옵션)
    if [ "$delete_bucket" = true ]; then
        delete_s3_bucket
    else
        log_info "S3 버킷을 유지합니다. 삭제하려면: $0 delete-bucket"
    fi

    log_success "=== 전체 삭제 완료 ==="
}

# 함수: 초기화 (S3 버킷만 생성)
init_setup() {
    log_info "=== NetAIOps 초기 설정 ==="
    echo ""

    # AWS 자격 증명 확인
    log_info "AWS 자격 증명 확인 중..."
    local account_id=$(get_aws_account_id)
    log_success "AWS 계정 ID: $account_id"
    log_info "AWS 리전: $AWS_REGION"
    echo ""

    # S3 버킷 생성
    ensure_s3_bucket

    echo ""
    log_success "초기 설정 완료!"
    log_info "이제 './deploy.sh deploy-all' 명령으로 배포할 수 있습니다."
}

# 메인 로직
main() {
    local command="${1:-}"
    local db_password="ReInvent2025!"
    local extra_args=""

    # 옵션 파싱
    shift || true
    while [[ $# -gt 0 ]]; do
        case $1 in
            --region) AWS_REGION="$2"; shift 2 ;;
            --db-password) db_password="$2"; shift 2 ;;
            --s3-bucket) S3_BUCKET_NAME="$2"; shift 2 ;;
            --delete-bucket) extra_args="--delete-bucket"; shift ;;
            -h|--help) show_usage; exit 0 ;;
            *) shift ;;
        esac
    done

    case "$command" in
        deploy-all)       deploy_all "$db_password" ;;
        deploy-base)      deploy_base "$db_password" ;;
        deploy-nfm)       deploy_nfm ;;
        deploy-cognito)   deploy_cognito ;;
        deploy-modules)   deploy_modules ;;
        deploy-traffic)   deploy_traffic ;;
        delete-all)       delete_all "$extra_args" ;;
        delete)           delete_stack "$2" ;;
        delete-bucket)    delete_s3_bucket ;;
        cleanup-templates) cleanup_s3_templates ;;
        status)           show_status ;;
        list)             show_status ;;
        init)             init_setup ;;
        -h|--help|"")     show_usage ;;
        *)                log_error "알 수 없는 명령: $command"; show_usage; exit 1 ;;
    esac
}

main "$@"
