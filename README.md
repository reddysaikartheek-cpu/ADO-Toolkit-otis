# ADO Tool Kit

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

### Generate Heatmap
- Exports the work items from a saved query URL or a WIQL query to an Excel heatmap file.
- Use the **Download Excel** button to save the file.

### Link Test Cases to Epic/Feature
- Lists the test cases from an Area Path, or from a Test Plan suite, with their link status to an Epic or Feature.
- Shows the Epic/Feature title and the test case count before any change.
- Click **Link test cases** to link the test cases that are not yet linked. The result shows how many were linked and how many were already linked.

### Create New Test Suite by Epics/Feature
- Finds the Epics and Features from a saved query URL, and lets you pick one.
- Shows the test cases linked to the selected Epic/Feature.
- Creates a static test suite in a Test Plan under the Parent suite you enter, and adds those test cases to it.
- The suite name follows the selected Epic/Feature. You can edit it before creating the suite.

### Dashboards
- Counts the Epics and Features from a saved query URL that have linked test cases and those that do not.
- Shows a coverage donut chart and two tables: with and without linked test cases.

### Epics/Features expected by sprint
- Shows the Epics expected in each sprint. An Epic's expected sprint is the last sprint among its child Features.
- Shows the Features in each sprint when the saved query contains Features.
- Titles containing SST are excluded.

### Pipelines
- Lists build runs for a pipeline, with optional branch and days-back filters, and a result filter.
- Shows a pass rate trend and the test results (passed, failed, failing test names) for a selected run.
- Lists classic release and YAML environment deployments.
- Queues a pipeline run on a branch you enter.
- Download the runs and deployments tables as CSV.

## Notes
- The saved query URL is entered in each tab that uses it. The value is shared across those tabs.
- The Pipelines tab reads the SmartSystems project. The other tabs use Otis ONE Platform.
- The app uses your PAT for all Azure DevOps calls. Keep `config.json` private and do not share it.
- The PAT needs Build (Read & execute), Test Management (Read), and Release (Read) scopes for the Pipelines tab.
- Static suites do not update when links change. Create a new suite to pick up new links.
- Run from source with `py -m streamlit run app.py` from the project folder.
