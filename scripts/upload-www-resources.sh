#!/usr/bin/env bash -eu

STORAGE_BUCKET_NAME=$(aws cloudformation describe-stacks --stack-name sauerpod-storage-stack --query "Stacks[0].Outputs[?OutputKey=='StorageBucketNameCfn'].OutputValue" --output text)
RESOURCES_PATH="${BASH_SOURCE%/*}/../resources/www"

echo "Bucket ${STORAGE_BUCKET_NAME}:"
aws s3 cp "${RESOURCES_PATH}" "s3://${STORAGE_BUCKET_NAME}" --recursive
