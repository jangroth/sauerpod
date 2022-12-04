#!/usr/bin/env bash -eux

# exit 1 # really!?

STORAGE_BUCKET_NAME=$(aws cloudformation describe-stacks --stack-name sauerpod-storage-stack --query "Stacks[0].Outputs[?OutputKey=='StorageBucketName'].OutputValue" --output text)
STORAGE_TABLE_NAME=$(aws cloudformation describe-stacks --stack-name sauerpod-storage-stack --query "Stacks[0].Outputs[?OutputKey=='StorageTableName'].OutputValue" --output text)

aws s3 rm "s3://${STORAGE_BUCKET_NAME}" --recursive

aws dynamodb scan \
  --attributes-to-get EpisodeId TimestampUtc \
  --table-name $STORAGE_TABLE_NAME --query "Items[*]" |
  jq --compact-output '.[]' |
  tr '\n' '\0' |
  xargs -0 -t -I keyItem aws dynamodb delete-item --table-name $STORAGE_TABLE_NAME --key=keyItem
