# leadbot setup (about 10 minutes, once)

1. Create a free GitHub account, then a **new public repo** (e.g. `leadbot`) and upload everything in this folder (drag and drop works, include the `.github` folder).
2. Repo **Settings > Pages**: Source = "Deploy from a branch", Branch = `main`, folder = `/docs`.
3. Gmail: turn on 2-step verification, then create an **App Password** (Google Account > Security > App passwords).
4. Repo **Settings > Secrets and variables > Actions**:
   - Secrets: `SMTP_USER` (your Gmail), `SMTP_PASS` (the app password)
   - Variables: `CITY` (e.g. Karachi), `CATEGORIES` (e.g. restaurant,cafe,bakery,hairdresser), `SENDER_NAME`, `SENDER_ADDRESS`, and `DRY_RUN` = `true` for the first run
5. **Actions tab > leadbot > Run workflow.** Check the generated pages and `leads.json`. Then set `DRY_RUN` = `false`.

After that it runs every day at 06:00 UTC: finds up to 10 new places, builds their sites, and emails those with a public email the next day.
To unsubscribe someone who replies "stop", add their email to `unsubscribed.txt`.
