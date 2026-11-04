# HB TOP UP (Python + Render)

## Before deployment
1. Revoke the Telegram bot token previously shared in chat using BotFather and create a new one.
2. Rotate the Pinbot API key previously shared. Do not commit either secret to GitHub.
3. In `bot.py`, replace `PASTE_NEW_BOT_TOKEN_HERE` and `PASTE_NEW_PINBOT_API_KEY_HERE` locally. (Better: set them in Render environment variables and modify constants accordingly.)
4. Set `PUBLIC_URL` automatically from Render's `RENDER_EXTERNAL_URL`.
5. Set `TELEGRAM_WEBHOOK_SECRET` in Render to a long random value.
6. Deploy using `render.yaml`. Persistent disk requires a paid Render service; free instances may not support persistent disk and can lose SQLite data.

## Admin commands in the Admin Panel
- Products & Prices: `PRICE product_id amount`, `ON product_id`, `OFF product_id`
- Force Join: `ADD @channel`, `DEL @channel`
- Admin IDs: edit `ADMIN_IDS` in `bot.py`.

## Important API limitations
- Product prices/costs are initialized as 0. Admin must set each selling price before users can order.
- API costs are read from Pinbot's response `total`; never hardcode supplier prices.
- `/tp` is asynchronous and needs Pinbot to POST its callback to `/pinbot/callback`. Confirm the callback URL contract with Pinbot support.
- `/getinfo` parameter format and accepted region codes were not fully specified, so UID/name pre-check is not implemented.
- Auto payment uses `/verify` exactly as supplied. It only works if the merchant account has BDT gateway verification enabled.
- The docs supplied show UC/shell/Indo item references but do not fully specify every endpoint/region mapping. Verify test orders with Pinbot before selling.
- The sample implementation uses the provided `/topup` endpoint for likes; confirm whether your merchant API key supports this endpoint.
- This is a starter production-oriented implementation, not a guarantee of provider compatibility. Test with tiny transactions first.
