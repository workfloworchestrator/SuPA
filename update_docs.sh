#!/usr/bin/env bash

# build the docs
cd docs
make clean
make html
cd ..

# stash
git stash

# switch branches and pull the data we want
git checkout gh-pages
rm -rf .
touch .nojekyll
git checkout master .gitignore
git checkout master docs/_build/html
mv ./docs/_build/html/* ./
rm -rf ./docs
git add -A
git commit -m "publishing updated docs..."
git push origin gh-pages
#
## switch back
git checkout master
git stash pop
