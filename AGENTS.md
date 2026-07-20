# Purpose

This repo uses Python to login MyUSCIS and check case status.
The pipeline is:
- Create a web session
- Login `https://my.uscis.gov/account/applicant`.
    - Authentication needs email, password, and TOTP. They are provided in `config.toml`.
- Check case status using `https://my.uscis.gov/account/case-service/api/cases/<receipt_number>`.
    - It returns a JSON (a dict), and the important field is `events`.

There might be multiple accounts defined in `config.toml`. Use CLI to select.

# Python

The Python virtual environment is under the `.venv` under the working directory.

When coding, assume the Python version is above 3.12. No need to make it compatible with older versions.

Type hints are preferred. When doing hints for native classes, use the typing categories.

For paths, use pathlib.Path.
