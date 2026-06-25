---
name: Data Analysis
module_id: skill.bundled.data_analysis
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "analyze this data"
    confidence: 0.85
  - pattern: "what does this data show"
    confidence: 0.80
  - pattern: "data analysis"
    confidence: 0.75
  - pattern: "trend.*data"
    confidence: 0.70
capabilities: [data-analysis, csv-processing, statistical-analysis, visualization]
trust_level: workspace
enabled_by_default: true
stability: stable
---

# Data Analysis

Analyze structured data (CSV, JSON, or tabular text) to extract insights, trends, and anomalies.

## When to Use
This skill activates when the user shares a dataset and asks for analysis, trends, or statistical insights. Best for:
- CSV/TSV file analysis
- JSON data exploration
- Log pattern analysis
- Numerical trend detection
- Comparison across categories

## Procedure

### Step 1: Load Data
1. Read the data file using `FileTool`
2. Parse the format (CSV via csv module, JSON via json module)
3. Display the shape (rows × columns) and column names
4. Show first 5 rows as a preview

### Step 2: Clean & Validate
1. Check for missing values and report counts per column
2. Identify data types (numeric, categorical, datetime)
3. Flag any obvious outliers or anomalies
4. Normalize formats if needed (dates, currency, units)

### Step 3: Analyze
1. Compute summary statistics (mean, median, min, max, std) for numeric columns
2. Count frequencies for categorical columns
3. Calculate correlations between numeric columns
4. Detect trends over time if a date column exists
5. Identify top/bottom values for key metrics

### Step 4: Synthesize
1. Write a clear summary of the key findings (3-5 bullet points)
2. Highlight anomalies, outliers, or unexpected patterns
3. Provide actionable recommendations based on the data
4. Include relevant numbers to support each finding

## Example

**Input:** `analyze sales_data.csv`
```
Month,Revenue,Customers,Region
Jan,45000,320,North
Feb,42000,310,North
Mar,48000,345,North
Apr,52000,360,South
May,58000,390,South
Jun,62000,410,South
```

**Output:**
```
Data shape: 6 rows × 4 columns
No missing values found.

Key Findings:
- Revenue grew 37.8% from Jan ($45K) to Jun ($62K)
- South region (added Apr) averages $57.3K/mo vs North $45K/mo
- Customer count correlates strongly with revenue (r=0.99)
- Top month: Jun ($62K), Lowest: Feb ($42K)

Recommendation: Consider expanding South region operations
```

## Lessons Learned
- Always check for missing data first — it skews stats
- Use median instead of mean when outliers are present
- Revenue trends need at least 3 data points to be meaningful
- Correlations don't imply causation — mention this caveat
