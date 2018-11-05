# Voty - The Voting Platform of [VoltEuropa](https://www.volteuropa.org)

#### Travis Build Status

##### Master
(not implemented yet)
[![Build Status](https://travis-ci.org/DemokratieInBewegung/abstimmungstool.svg?branch=master)](https://travis-ci.org/DemokratieInBewegung/abstimmungstool)

##### Develop
(not implemented yet)
[![Build Status](https://travis-ci.org/DemokratieInBewegung/abstimmungstool.svg?branch=develop)](https://travis-ci.org/DemokratieInBewegung/abstimmungstool)

## Development 
This runs on Python Django. For Development, you'll need Python 3.0 and a virtual environment.

1. Installation
To install the packages required for a successful install on Ubuntu, run

```
sudo apt-get install python3-dev
sudo apt-get install virtualenv
sudo apt-get install postgresql postgresql-contrib
sudo apt-get install libpq-dev
sudo apt-get install libjpeg8-dev
```
On Mac OS X, run
```
brew install python3
sudo easy_install pip
sudo pip install virtualenv
brew update
brew install postgres
 ```
On a chromebook (developer mode, chromebrew installed), run
```
$ crew install python3
$ crew install virtualenv
$ crew install postgresql
$ echo 'export PGDATA="/usr/local/data/pgsql"' >> ~/.bashrc && source ~/.bashrc
```

2. Setup Localhost
To setup the latest version (on the Volt branch currently), please clone the repo,
create and activate a virtual environment and then setup voty:
```
$ git clone https://github.com/VoltEuropa/voty
$ git checkout -b volt <name of remote>/volt
$ virtualenv venv
$ source venv/bin/activate
(venv) $ pip install -r requirements.txt
(venv) $ python3 manage.py migrate
(venv) $ python3 manage.py set_quorum
(venv) $ python3 manage.py createsuperuser
(venv) $ python3 manage.py set_groups_and_permissions
(venv) $ python3 manage.py runserver
```
Note both `requirements.txt` and `manage.py` are in the same folder you'll have to navigate to. Once everything ran, the app will be available under `http://localhost:8000`, the admin interface is on `http://localhost:8000/admin/`. The server automatically refreshes when changes are made to the source code (aside from `init.ini` - requires a restart of the server).

## Deployment
(not tried) Using docker-compose, right from within this repo, run:

```
docker compose up
```

### Upgrade database

Don't forget to update the database after/within each deploy:
```
docker compose exec web bash /code/scripts/upgrade.sh
```

## License

This is released under AGPL-3.0. See the LICENSE-file for the full text.
