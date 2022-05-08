# this file must be source-d

TELEGRAM_API_TOKEN=$(aws ssm get-parameters --with-decryption --names "/sauerpod/telegram/api-token" --query 'Parameters[*].Value' --output text --region ap-southeast-2)
TELEGRAM_CHAT_ID=$(aws ssm get-parameters --with-decryption --names "/sauerpod/telegram/chat-id" --query 'Parameters[*].Value' --output text --region ap-southeast-2)

export TELEGRAM_API_TOKEN=$TELEGRAM_API_TOKEN
export TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID
