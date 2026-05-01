# Solution Co-Development Toolkit

## Overview
The **Solution Co-Development Toolkit** is a Django-based web application designed to facilitate the co-development of solutions, likely in the context of MSFC (possibly Marshall Space Flight Center or a similar organization, given the PDF filenames). The toolkit provides a structured digital interface for various stages of project planning and impact assessment, mirroring the content found in the accompanying toolkit PDF parts.

Key sections include:
- Designing for Impact
- Stakeholder Mapping & Analysis
- Needs Assessment
- User-Centered Design
- Data Governance & Storage
- Implementation & Sustainability planning

## Stack
- **Language:** Python
- **Framework:** [Django 6.0.4](https://www.djangoproject.com/)
- **Database:** SQLite (default)
- **Frontend:** Django Templates (HTML/CSS)

## Requirements
- Python 3.10+ (Recommended)
- Django 6.0.4

## Setup
1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd "Solution Co-Development Toolkit"
   ```

2. **Create a virtual environment (Optional but recommended):**
   ```bash
   python -m venv venv
   # On Windows:
   .\venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. **Install Dependencies:**
   *(Note: No requirements.txt found in repo. Minimal requirement is Django)*
   ```bash
   pip install django==6.0.4
   ```

4. **Initialize Database:**
   ```bash
   python manage.py migrate
   ```

## Run Commands
To start the development server locally:
```bash
python manage.py runserver
```
The application will be available at `http://127.0.0.1:8000/`.

## Scripts
- `python manage.py runserver`: Starts the development server.
- `python manage.py migrate`: Applies database migrations.
- `python manage.py collectstatic`: Collects static files for production (if configured).
- `python manage.py test`: Runs the test suite.

## Environment Variables
- `DEBUG`: Set to `True` for development, `False` for production in `settings.py`.
- `SECRET_KEY`: Django secret key for security (currently hardcoded in `settings.py`).
- **TODO:** Implement a `.env` file for managing sensitive configuration in production.

## Tests
To run the existing tests:
```bash
python manage.py test webapp
```
*(Note: Current tests in `webapp/tests.py` may be placeholders).*

## Project Structure
```text
.
├── manage.py                          # Django management script
├── solution_co_development_toolkit/   # Project configuration
│   ├── settings.py                    # Main settings
│   └── urls.py                        # Root URL routing
├── webapp/                            # Main application logic
│   ├── views.py                       # View controllers for toolkit sections
│   ├── urls.py                        # App-specific URL routing
│   └── tests.py                       # Unit tests
├── templates/                         # HTML Templates
│   ├── base.html                      # Base layout
│   └── webapp/                        # Toolkit section templates
├── MSFC_Toolkit_Part_*.pdf            # Supporting documentation (Parts 1-13)
├── start.pdf                          # Quick start guide / Introduction PDF
└── db.sqlite3                         # Local development database
```

## License
**TODO:** Specify license (e.g., MIT, Apache 2.0, or Proprietary). No LICENSE file found in repository.
