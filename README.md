# Okta-Import-Source

## Overview  
This is a Python program that queries whether a user is from a different source other than Okta and outputs the results into an Excel sheet.  
It is designed for performing import / audit / reconciliation tasks between an external source of user data and your Okta environment.

## Features  
- Connects to the external “source” system (CSV, database, API, etc) and retrieves user records.  
- Compares the source data against the Okta user directory.  
- Identifies users in the external source who are _not_ present in Okta (or differ in key fields).  
- Generates an output Excel sheet summarizing the findings.  
- Provides configuration options for source path, Okta domain/token, filters, and output file.

## Getting Started

### Prerequisites  
- Python 3.x installed.  
- Access to your Okta tenant with API token (read permissions).  
- Access or export of your external source of user data (CSV, database, etc).  
- Required Python libraries (see next section).

### Installation & Running
```bash
git clone https://github.com/Aquese/Okta-Import-Source.git
cd Okta-Import-Source
pip install -r requirements.txt
python main.py --config config.yaml
```
