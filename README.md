# 🤖 Telegram Contact Invite Bot

Automated bot that invites Telegram contacts to a specified group/channel using multiple sessions with intelligent contact sharing system.

## ✨ Features

- 🔄 **Automatic Scheduling**: Runs every 10 hours automatically
- 💾 **MongoDB Persistent Storage**: All data survives restarts (Render-compatible)
- 🤝 **Contact Sharing System**: High-contact users share with low-contact users
- ⚡ **Concurrent Processing**: Process 8 sessions simultaneously
- 🛡️ **Flood Protection**: Smart delays and batch processing
- 📊 **Real-time Statistics**: Track invitations and success rates
- 🔄 **No Duplicate Invites**: Tracks invited users per session

## 🗄️ MongoDB Collections

The bot creates these collections automatically:
- `sessions` - Your Telegram session strings (READ ONLY - never modified)
- `invited_users` - Tracks invited users per session
- `contact_pool` - Shared contact pool for cross-session sharing
- `bot_state` - Last run info and statistics

## 🚀 Deployment on Render

### Prerequisites
1. MongoDB Atlas account (free tier works)
2. Telegram API credentials (api_id, api_hash)
3. GitHub account
4. Render account (free tier works)

### Steps

1. **Clone/Fork this repository**
   ```bash
   git clone https://github.com/yourusername/telegram-invite-bot.git
   cd telegram-invite-bot
   ```

2. **Update Configuration in `main.py`**
   - Set your `API_ID` and `API_HASH`
   - Set your `GROUP_USERNAME`
   - Update MongoDB connection string
   - Adjust `RUN_INTERVAL_HOURS` (default: 10 hours)

3. **Push to GitHub**
   ```bash
   git add .
   git commit -m "Initial commit"
   git push origin main
   ```

4. **Deploy on Render**
   - Go to [Render Dashboard](https://dashboard.render.com/)
   - Click "New +" → "Web Service"
   - Connect your GitHub repository
   - Configure:
     - **Name**: telegram-invite-bot
     - **Environment**: Python 3
     - **Build Command**: `pip install -r requirements.txt`
     - **Start Command**: `python main.py`
     - **Plan**: Free
   - Click "Create Web Service"

5. **Verify Deployment**
   - Check logs for "Flask server started"
   - Visit `https://your-app.onrender.com/health` to see status
   - Bot will start running every 10 hours automatically

## ⚙️ Configuration

Edit these variables in `main.py`:

```python
# Telegram API
API_ID = 'your_api_id'
API_HASH = 'your_api_hash'

# Target Group
GROUP_USERNAME = "your_group_username"

# Scheduler
RUN_INTERVAL_HOURS = 10  # Run every 10 hours

# Session Range (optional)
START_SESSION = 1        # Start from session 1
END_SESSION = None       # Process all sessions

# Concurrency
MAX_CONCURRENT_SESSIONS = 8
BATCH_SIZE = 50

# Contact Sharing
ENABLE_CONTACT_SHARING = True
MIN_CONTACTS_FOR_SHARING = 1000
LOW_CONTACT_THRESHOLD = 700

# Invitations
CONTACT_INVITE_BATCH_SIZE = 33
MAX_CONTACTS_TO_INVITE = 99
```

## 📊 Monitoring

### Health Check Endpoint
```bash
curl https://your-app.onrender.com/health
```

Response:
```json
{
  "status": "healthy",
  "last_run": {
    "last_run": "2024-01-15T10:30:00",
    "next_run": "2024-01-15T20:30:00",
    "success_count": 45,
    "failed_count": 5,
    "total_time_minutes": 12.5
  }
}
```

### View Logs
- Go to Render Dashboard → Your Service → Logs
- Monitor real-time bot activity

## 🔒 Security Notes

- ✅ Session strings are READ ONLY (never modified)
- ✅ All sensitive data stored in MongoDB (not in code)
- ✅ Use environment variables for API credentials (recommended)
- ✅ Add `.env` file to `.gitignore`

## 🛠️ Troubleshooting

### Bot not running every 10 hours?
- Check Render logs for errors
- Verify Flask server is running (keeps service alive)
- Ensure MongoDB connection is active

### Sessions not working?
- Verify session strings in MongoDB are valid
- Check if 2FA is enabled (bot will skip those)
- Look for "AuthKeyUnregisteredError" in logs

### MongoDB connection issues?
- Verify connection string is correct
- Check MongoDB Atlas network access (allow all IPs: 0.0.0.0/0)
- Ensure database user has read/write permissions

## 📝 License

MIT License - Feel free to use and modify

## 🤝 Contributing

Pull requests are welcome! For major changes, please open an issue first.

## ⚠️ Disclaimer

This bot is for educational purposes. Use responsibly and comply with Telegram's Terms of Service. Excessive invitations may result in account restrictions.

