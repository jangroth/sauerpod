# SauerPod (WIP)
![SauerPod](.media/sauerpod.drawio.png)

A grumpy bot that downloads videos into a personalized podcast.

## Development setup
### Ramp Up
* Telegram
    * Create bot
        * Get bot id from botfather
    * Create chat
        * Get chat.id from @RawDataBot
* `./scripts/bootstrap-secrets.sh`
### Prepare dev environment
* Create/activate venv
* Deploy stack (or `cdk watch`)
* Point bot`s webhook to Lambda
    * Source secrets
        `. ./scripts/get-secrets-from-ssm.sh`
    * Update web url at bot
        `./scripts/update-web-url-at-bot.sh`


## Resources
* https://core.telegram.org/bots/api
* https://xabaras.medium.com/setting-your-telegram-bot-webhook-the-easy-way-c7577b2d6f72
