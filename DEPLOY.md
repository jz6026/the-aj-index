# Putting The AJ Index on AWS

How the site runs on AWS, and how to deploy it from my Mac. The whole setup is code in
[`infra/stack.py`](infra/stack.py) (AWS CDK, in Python), so one command builds everything
and one command tears it all down.

```
browser ──> CloudFront ──┬──> S3                     the website (web/)
                         └──> /api/* ─> load balancer ─> ECS Fargate   the API (ajworth/api.py)
                                                          │
EventBridge, daily ──> ECS task: ajworth.fetch ───────────┴──> RDS Postgres
```

| Piece | AWS service | What it does |
|---|---|---|
| Website files | S3 + CloudFront | Serves `web/` over HTTPS, and forwards `/api/*` to the API |
| API | ECS on Fargate, behind a load balancer | Runs the Docker image. No servers to babysit |
| Database | RDS Postgres (db.t4g.micro) | Private, no internet access, login kept in Secrets Manager |
| Wiki refresh | EventBridge + an ECS task | Runs `python -m ajworth.fetch` every morning |
| Budget alert | AWS Budgets | Emails me at 50% / 80% of my monthly limit |

It's the same layout as `docker compose` on my Mac (db / api / web / refresh), just the AWS versions.

## What it costs (ballpark, check before you deploy!)

Rough monthly numbers for us-east-1 if it's left running 24/7. Prices change, so double-check with
the [AWS Pricing Calculator](https://calculator.aws/).

| Thing | ~$/month |
|---|---|
| Load balancer | ~16 |
| Public IPv4 addresses (load balancer + API container) | ~11 |
| RDS db.t4g.micro + 20 GB storage | ~14 |
| Fargate API (0.25 vCPU, 0.5 GB, ARM) | ~7 |
| Secrets Manager, CloudFront, S3, logs, the daily job | ~1 |
| **Total** | **~$50** |

So the $200 new-account credits last about 4 months. Ways to stretch them:
- `cdk destroy` when I'm not actively using it, and redeploy later (data comes back from the wiki with one refresh)
- the budget alert (step 4) so nothing sneaks up on me

Heads up on the AWS **Free plan**: when the credits run out or 6 months pass, the account just closes.
Some services might also be limited on that plan, so if a deploy fails with an "account plan" error,
switch to the Paid plan (the credits still apply, and the budget alert still protects me).

## One-time setup

1. **AWS account.** Make one at aws.amazon.com. Then make an everyday admin login through
   IAM Identity Center instead of using the root email login for everything.
2. **Tools on my Mac:**
   ```bash
   brew install awscli node
   npm install -g aws-cdk
   ```
   Plus [Docker Desktop](https://www.docker.com/products/docker-desktop/), which needs to be **running** whenever I deploy
   (CDK builds the image with it).
3. **Log the CLI in:**
   ```bash
   aws configure sso            # follow the prompts, pick region us-east-1
   aws sts get-caller-identity  # should print my account number
   ```
   (if I named the profile something, add `--profile thatname` to the aws/cdk commands, or `export AWS_PROFILE=thatname`)
4. **CDK's Python bits + one-time "bootstrap"** (sets up a bucket CDK uses for uploads):
   ```bash
   cd infra
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   cdk bootstrap
   ```

## Deploying

From `infra/` with the venv on:

```bash
cdk deploy -c alert_email=MY_EMAIL
```

The first deploy takes ~15–20 minutes (the database and CloudFront are slow to create). It prints
**SiteUrl** at the end, so open that. AWS also sends a quick email to confirm the budget alerts.

### Loading the data the first time

The refresh runs on its own every morning, but to fill the database right away, I can run it by hand.
Plug in the values that `cdk deploy` printed:

```bash
aws ecs run-task \
  --cluster CLUSTER_NAME \
  --task-definition REFRESH_TASK_DEF \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[FIRST_PUBLIC_SUBNET],securityGroups=[REFRESH_SG],assignPublicIp=ENABLED}"
```

It takes a few minutes (it waits 1s between wiki requests on purpose). Then search for an item on the site.

### Changing stuff later

- Changed Python code, `web/`, or the Dockerfile? Just `cdk deploy` again. It rebuilds the image, swaps in
  the new version without downtime, and rolls back by itself if the new one fails its health check.
- `cdk diff` shows what a deploy *would* change before doing it.

### Seeing what's going on

- **Logs:** CloudWatch → Log groups → the ones starting with `AjIndex` (one for the API, one for the refresh job). Or:
  ```bash
  aws logs describe-log-groups --log-group-name-prefix AjIndex --query "logGroups[].logGroupName"
  aws logs tail THAT_LOG_GROUP --follow
  ```
- **Is the API alive?** `SiteUrl/api/health` should say `{"ok":true}`.
- **Costs:** Billing → Cost Explorer, filter by the tag `project = the-aj-index`.

## Tearing it down

```bash
cdk destroy
```

This deletes everything except a final snapshot of the database (just in case). If I don't need it,
delete it in RDS → Snapshots so it doesn't keep costing a little bit.

## Not done yet (before a real launch)

- **Lock the load balancer to CloudFront.** Right now someone could hit the API's load balancer address
  directly and skip CloudFront. Fix: only allow CloudFront's IP list (the `com.amazonaws.global.cloudfront.origin-facing` prefix list) on the load balancer.
- **Rate limits for the chatbot,** so one person (or a bot) can't run up the bill.
- **My own domain** (Route 53 + a free HTTPS certificate from ACM) instead of the `cloudfront.net` address.
- **Auto-deploy from GitHub** (GitHub Actions runs the tests, then `cdk deploy`).
- **Login** with Amazon Cognito, when the features that need accounts are ready (see ROADMAP).
