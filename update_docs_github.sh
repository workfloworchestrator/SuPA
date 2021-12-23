#!/usr/bin/env bash

# build the docs
cd docs
make clean
make html
cd ..

# stash
git stash

# switch branches and pull the data we want
git checkout -b gh-pages
rm -rf *
touch .nojekyll
git checkout master .gitignore
git checkout master docs/_build/html
mv ./docs/_build/html/* ./
rm -rf ./docs
git config user.email "admin@workfloworchestrator.org"
git config user.name "Admin"
git add -A
git commit -m "publishing updated docs..."
git push origin gh-pages
