# Quickdash Project Backend

[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://python.org/)
[Project Repository](https://github.com/Mdhelaluddin3391/quickdash_project_backend)

A Django-based web application powering order management, inventory, user accounts, delivery, cart, store operations, and support ticketing for the Quickdash project.

---

## Table of Contents
- [Features](#features)
- [Project Structure](#project-structure)
- [Main Apps Overview](#main-apps-overview)
- [Setup & Installation](#setup--installation)
- [Usage](#usage)
- [API & Endpoints](#api--endpoints)
- [Testing](#testing)
- [License](#license)
- [Contributing](#contributing)

---

## Features

- **Order Management & Cart:** Full shopping cart, checkout, order fulfillment workflows.
- **Inventory:** Item tracking, stock management, warehouse module.
- **User Accounts:** Authentication, permissions, user profile management.
- **Delivery System:** Assign, track, and resolve delivery tasks.
- **Store Management:** Product, category, and retail store CRUD.
- **Support System:** Raise, track, and resolve support tickets/issues.
- **Admin Dashboard:** Operations, business insights, and manual overrides.
- **Extensible with Django apps:** Modular architecture for easy updates.

---

## Project Structure

```
quickdash_project_backend/
├── accounts/      # User auth, profiles
├── cart/          # Shopping carts
├── dashboard/     # Admin operations & views
├── delivery/      # Delivery workflows
├── inventory/     # Products, stock, warehouse
├── orders/        # Order flow, packing, refund
├── quickdash/     # Main Django settings
├── store/         # Product, store & category endpoints
├── support/       # Support tickets/issues
├── wms/           # Warehouse management
├── manage.py      # Django management script
```

---

## Main Apps Overview

- **accounts:** Handles user authentication, registration, profile, permissions.
- **cart:** Implements cart operations (add/remove/update items), checkout session.
- **dashboard:** Staff/admin views, task management, manual packing, dashboard analytics.
- **delivery:** Delivery assignment, reporting, tracking, and resolution.
- **inventory:** Product DB, categories, warehouse stock, item CRUD.
- **orders:** Order lifecycle, packing, refund logic, picking/packing API endpoints.
- **store:** Data models & APIs for retail locations and categories.
- **support:** Support ticket model & workflow, issue reporting and resolution.
- **wms:** Warehouse Management System helpers and APIs.

---

## Setup & Installation

### Requirements
- Python 3.8+
- Django 3.2+
- pip
- (Optional) PostgreSQL or SQLite

### Installation Steps
1. **Clone the repository**
   ```sh
   git clone https://github.com/Mdhelaluddin3391/quickdash_project_backend.git
   cd quickdash_project_backend
   ```

2. **Install dependencies**
   ```sh
   pip install -r requirements.txt
   ```

3. **Apply migrations**
   ```sh
   python manage.py migrate
   ```

4. **Run the development server**
   ```sh
   python manage.py runserver
   ```

5. **Create superuser (for admin dashboard):**
   ```sh
   python manage.py createsuperuser
   ```

---

## Usage

- Access `/admin/` for admin dashboard.
- All main endpoints are versioned and mapped in their respective apps (see cart/, orders/, dashboard/, etc.).
- API is RESTful and JSON-based; authentication required for sensitive actions.

---

## API & Endpoints

- Cart operations (`/cart/`)
- Orders (`/orders/`)
- Delivery tasks & reports (`/delivery/`)
- Admin dashboard actions (`/dashboard/`)
- Product, store & warehouse CRUD (`/store/`, `/inventory/`, `/wms/`)
- Support ticket APIs (`/support/`)
- User account actions (`/accounts/`)
- See in-app docs/comments or browse app folders for specific API paths.

---

## Testing

- Run unit tests via:
  ```sh
  python manage.py test
  ```
- Major flows covered in `dashboard/tests.py` and additional test files in apps.
- Extend with more tests for new features and critical logic.

---

## License

This project currently does not specify a license. Please update with your chosen license.

---

## Contributing

Pull requests and issues are welcome!

1. Fork the repo
2. Create your feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes (`git commit -am 'Add new feature'`)
4. Push to the branch (`git push origin feature/my-feature`)
5. Open a Pull Request

---

Contact: [Mdhelaluddin3391](https://github.com/Mdhelaluddin3391)

---
