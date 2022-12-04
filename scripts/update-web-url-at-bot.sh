#!/usr/bin/env bash
set -eux

BOUNCER_URL=$(aws cloudformation describe-stacks --query 'Stacks[?StackName==`sauerpod-logic-stack`][].Outputs[?OutputKey==`BouncerUrl`].OutputValue' --output text)

if [[ -z "${TELEGRAM_API_TOKEN}" ]] || [[ -z "${BOUNCER_URL}" ]]; then
    echo 'Missing environment configuration, exiting.'
    exit 1
fi

# https://core.telegram.org/bots/api#setwebhook
curl "https://api.telegram.org/bot${TELEGRAM_API_TOKEN}/setWebhook?url=${BOUNCER_URL}&drop_pending_updates=True&max_connections=2"
