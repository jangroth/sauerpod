#!/usr/bin/env bash -eux

TELEGRAM_API_TOKEN="value"
TELEGRAM_CHAT_ID="value"

if [[ $TELEGRAM_API_TOKEN=='value' || $TELEGRAM_CHAT_ID=='value' ]]; then
    echo 'Need to insert values!'
fi

aws ssm put-parameter \
    --name '/sauerpod/telegram/api-token' \
    --value ${TELEGRAM_API_TOKEN} \
    --type SecureString \
    --overwrite \
    --region 'ap-southeast-2'

aws ssm put-parameter \
    --name '/sauerpod/telegram/chat-id' \
    --value ${TELEGRAM_CHAT_ID} \
    --type String \
    --overwrite \
    --region 'ap-southeast-2'
