#!/usr/bin/env bash -eu

STORAGE_BUCKET_NAME=$(aws cloudformation describe-stacks --stack-name sauerpod-storage-stack --query "Stacks[0].Outputs[?OutputKey=='StorageBucketName'].OutputValue" --output text)
STORAGE_TABLE_NAME=$(aws cloudformation describe-stacks --stack-name sauerpod-storage-stack --query "Stacks[0].Outputs[?OutputKey=='StorageTableName'].OutputValue" --output text)

echo "Bucket ${STORAGE_BUCKET_NAME}:"
aws s3 ls "s3://${STORAGE_BUCKET_NAME}" --recursive

echo -e "\nTable ${STORAGE_TABLE_NAME}:"
aws dynamodb scan \
  --attributes-to-get EpisodeId TimestampUtc Title --table-name $STORAGE_TABLE_NAME --query "Items[*]" |
  jq --compact-output '.[]'

echo
