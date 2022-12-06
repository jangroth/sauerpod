#!/usr/bin/env bash -eu

STORAGE_BUCKET_NAME=$(aws cloudformation describe-stacks --stack-name sauerpod-storage-stack --query "Stacks[0].Outputs[?OutputKey=='StorageBucketName'].OutputValue" --output text)

echo "Bucket ${STORAGE_BUCKET_NAME}:"

aws s3 cp "s3://${STORAGE_BUCKET_NAME}/default-feed.rss" .
