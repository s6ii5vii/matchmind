# Deploying MatchMind to Azure

MatchMind ships as **one container**: the dashboard is built to static files and the Python API serves them, so the whole app lives at one URL. It runs on **Azure Container Apps**.

Allow about 20 minutes the first time. Commands are for PowerShell on Windows, run from the repository folder.

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

## 2. Build and deploy

```powershell
az containerapp up `
  --name matchmind `
  --resource-group matchmind-rg `
  --location swedencentral `
  --source . `
  --ingress external `
  --target-port 8000
```

This builds the `Dockerfile` in Azure (no Docker needed on your computer), creates the app and prints its URL, something like `https://matchmind.<random>.swedencentral.azurecontainerapps.io`. The first run takes 5-10 minutes.

- `matchmind-rg` is the resource group you created for Foundry. Any name works.
- To build, Azure creates a small container registry, which costs about $5 a month. Delete the resource group after the hackathon to stop all charges (see the end of this guide).

Open the URL. The app works straight away with the rule-based agents.

## 3. Add the AI model key

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

## 4. Updating after code changes

Run the same `az containerapp up` command from step 2 again. Secrets and settings are kept.

## 5. Before judges look at it

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

## 6. After the hackathon

```powershell
az group delete --name matchmind-rg
```

This deletes everything in the group: the app, the registry and the Foundry resource. Only run it when you're done with all of them.

## Run the container yourself (optional)

With Docker Desktop installed:

```powershell
docker build -t matchmind .
docker run -p 8000:8000 --env-file backend/.env matchmind
```

Then open http://localhost:8000.
