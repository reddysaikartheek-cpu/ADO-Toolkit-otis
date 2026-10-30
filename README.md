# Azure DevOps Toolkit

A small local web app for working with Azure DevOps Test Plans, Epics, Features, and Test Cases.

## Setup

1. Place `config.json` next to the app (or exe) with your PAT:

   ```json
   { "pat": "<your-personal-access-token>" }
   ```

   You can also set the `AZDO_PAT` environment variable instead.
2. Keep `default_query.wiql` next to the app. It pre-fills the WIQL boxes.
3. Run `AzureDevOpsToolkit.exe` (from the `AzureDevOpsToolkit` folder), then open the URL it shows (usually http://localhost:8501).

## Features

### Generate Heatmap
- Exports the work items from a saved query URL or a WIQL query to an Excel heatmap file.
- Use the **Download Excel** button to save the file.

### Link Test Cases to Epic
- Lists the test cases from an Area Path, or from a Test Plan suite, with their link status to an Epic.
- Shows the Epic title and the test case count before any change.
- Click **Link test cases** to link the test cases that are not yet linked. The result shows how many were linked and how many were already linked.

### List of Epics/Features with no linked Test cases
- Checks the Epics and Features from a saved query or WIQL query.
- Lists the ones that have no linked test cases. Click an ID to open it in Azure DevOps.

### Create New Test Suite by Epics/Feature
- Finds the Epics and Features from a saved query or WIQL query, and lets you pick one.
- Shows the test cases linked to the selected Epic/Feature.
- Creates a static test suite in a Test Plan under the Parent suite you enter, and adds those test cases to it.
- The suite name follows the selected Epic/Feature. You can edit it before creating the suite.

## Notes
- The app uses your PAT for all Azure DevOps calls. Keep `config.json` private and do not share it.
- Static suites do not update when links change. Create a new suite to pick up new links.
- Run from source with `py -m streamlit run app.py` from the project folder.
