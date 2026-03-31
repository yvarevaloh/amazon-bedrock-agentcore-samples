#!/bin/bash
set -e

REGION="us-west-2"
STACK_NAME="host-agent"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO_NAME="host-agent-ecr"
IMAGE_TAG="build-1"
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO_NAME}"
AGENT_DIR="$(cd "$(dirname "$0")/../host_adk_agentclaude" && pwd)"
TEMPLATE="$(dirname "$0")/host_agent_local.yaml"

# Validate required params
COGNITO_STACK="${1:-cognito}"

echo "=== Step 1: Create ECR repository ==="
aws ecr create-repository --repository-name "$ECR_REPO_NAME" --region "$REGION" 2>/dev/null || echo "ECR repo already exists"

echo "=== Step 2: Build Docker image locally ==="
echo "Building from: $AGENT_DIR"
docker build -t bedrock-agentcore-arm64 "$AGENT_DIR"

echo "=== Step 3: Push to ECR ==="
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
docker tag bedrock-agentcore-arm64:latest "${ECR_URI}:${IMAGE_TAG}"
docker push "${ECR_URI}:${IMAGE_TAG}"

echo "=== Step 4: Deploy CloudFormation stack ==="
aws cloudformation create-stack \
  --stack-name "$STACK_NAME" \
  --template-body "file://${TEMPLATE}" \
  --parameters \
    ParameterKey=ContainerImageUri,ParameterValue="${ECR_URI}:${IMAGE_TAG}" \
    ParameterKey=CognitoStackName,ParameterValue="$COGNITO_STACK" \
  --capabilities CAPABILITY_IAM \
  --region "$REGION"

echo "=== Waiting for stack creation ==="
aws cloudformation wait stack-create-complete --stack-name "$STACK_NAME" --region "$REGION"

echo "=== Done! ==="
aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" --query "Stacks[0].Outputs" --output table
