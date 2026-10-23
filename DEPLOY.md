# Deploying MatchMind to Azure

MatchMind ships as **one container**: the dashboard is built to static files and the Python API serves them, so the whole app lives at one URL. It runs on **Azure Container Apps**.

Allow about 20 minutes the first time. Commands are for PowerShell on Windows. Run them one at a time.

## 1. Install the Azure CLI (once)

```powershell
winget install -e --id Microsoft.AzureCLI
```

Close and reopen the terminal afterwards, then sign in and add the Container Apps tools:

```powershell
az login
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
```

`az login` opens the browser; sign in with the account that has your Azure subscription.

## 2. Let GitHub build the container

Every merge to `main` runs the [Test and build](.github/workflows/container.yml) workflow. It runs the tests, builds the container and publishes it to GitHub's container registry as `ghcr.io/s6ii5vii/matchmind`. Azure runs that ready-made image, so nothing is built in Azure. (Free-trial Azure subscriptions aren't allowed to build images there: the `TasksOperationsNotAllowed` error.)

1. On GitHub, open the repository's **Actions** tab and wait for **Test and build** to go green on the latest commit to `main` (about 3-5 minutes).
2. **Make the image public, once**, so Azure can download it without a password:
   1. Go to your GitHub profile, then **Packages**, then **matchmind**.
   2. Open **Package settings**.
   3. Under **Danger Zone**, choose **Change visibility**, then **Public**.

   The image holds only the app's code and no keys.

## 3. Deploy

```powershell
az containerapp up `
  --name matchmind `
  --resource-group matchmind-rg `
  --location swedencentral `
  --image ghcr.io/s6ii5vii/matchmind:latest `
  --ingress external `
  --target-port 8000
```

This creates the app (and its environment, the first time) and prints its URL, something like `https://matchmind.<random>.swedencentral.azurecontainerapps.io`. Open it: the app works straight away with the rule-based agents.

## 4. Add the AI model key

Keys are stored as Container Apps **secrets**, never in the code. Pick one provider.

**Nebius Token Factory:**

```powershell
az containerapp secret set -n matchmind -g matchmind-rg --secrets nebius-key=YOUR_NEBIUS_KEY
az containerapp update -n matchmind -g matchmind-rg `
  --set-env-vars NEBIUS_API_KEY=secretref:nebius-key NEBIUS_MODEL=openai/gpt-oss-120b
```

**Microsoft Foundry** (once you have a deployment):

```powershell
az containerapp secret set -n matchmind -g matchmind-rg --secrets azure-openai-key=YOUR_FOUNDRY_KEY
az containerapp update -n matchmind -g matchmind-rg `
  --set-env-vars AZURE_OPENAI_ENDPOINT=https://YOUR-RESOURCE.cognitiveservices.azure.com `
                 AZURE_OPENAI_DEPLOYMENT=YOUR-DEPLOYMENT-NAME `
                 AZURE_OPENAI_API_KEY=secretref:azure-openai-key
```

If both are set, Foundry is used. Check which one is live at `https://YOUR-URL/api/config` (`model_provider`), or in the Agent room header.

## 5. Updating after code changes

Merge to `main` and wait for **Test and build** to go green. Then point the app at the new image (each build is also tagged with its commit, so this always picks up the new one):

```powershell
az containerapp update -n matchmind -g matchmind-rg --image ghcr.io/s6ii5vii/matchmind:<commit-sha>
```

The full commit SHA is shown on the workflow run and on GitHub's commit page. Secrets and settings are kept.

## 6. Before judges look at it

By default the app sleeps when nobody is using it, so the first visit after a quiet spell takes 10-20 seconds to wake. For the judging period, keep one copy running (a few dollars for the week):

```powershell
az containerapp update -n matchmind -g matchmind-rg --min-replicas 1
```

Useful checks:

```powershell
# the app's URL
az containerapp show -n matchmind -g matchmind-rg --query properties.configuration.ingress.fqdn -o tsv
# recent logs, e.g. if the agents say "Model call failed"
az containerapp logs show -n matchmind -g matchmind-rg --tail 50
```

## 7. After the hackathon

```powershell
az group delete --name matchmind-rg
```

This deletes everything in the group: the app, its environment and the Foundry resource. Only run it when you're done with all of them.

## Run the container yourself (optional)

With Docker Desktop installed:

```powershell
docker build -t matchmind .
docker run -p 8000:8000 --env-file backend/.env matchmind
```

Then open http://localhost:8000.
