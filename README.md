# Failed Indian Startups Analytics Dashboard

Interactive Streamlit dashboard for high-level business analysis of failed Indian startups/MSMEs using `startups.xlsx`.

## GitHub Files

Upload all files from this folder to the root of your GitHub repository:

```text
app.py
requirements.txt
README.md
index.html
startups.xlsx
.gitignore
.streamlit/config.toml
```

## Features

- Executive KPI overview
- Shutdown and funding charts
- Sector and failure-category analysis
- Correlation heatmap
- Regression modeling and feature importance
- What-if prediction form
- Filterable data explorer with CSV export

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```powershell
streamlit run app.py
```

By default, the app first looks for this file in the same repository folder:

```text
startups.xlsx
```

If it is not there, it falls back to `C:\Users\hp\Desktop\startups.xlsx`. You can also change the file path from the dashboard sidebar.

## Deploy

For Streamlit Cloud:

1. Push/upload these files to GitHub.
2. Open Streamlit Cloud and create a new app from the repository.
3. Set the main file path to `app.py`.
4. Deploy.

`index.html` is included for GitHub Pages or a static repository landing page. The interactive dashboard itself runs with Streamlit.

## Notes

The workbook contains failed startups only, so the predictive section is not a survivor-vs-failure classifier. It predicts outcomes within the failed-company dataset, such as funding, losses, or other numeric business metrics.
