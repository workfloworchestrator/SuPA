#!/usr/bin/env bash

# check if working tree is clean
if git diff --quiet --exit-code
then
    : working tree is clean
else
    echo "working tree not clean, will not update docs"
    exit 1
fi

# build the docs
cd docs
make clean
make html
cd ..

# stash
git add docs/_build
git stash

# switch branches and pull the data we want
set -e
git checkout gh-pages
rm -rf *
git stash pop
touch .nojekyll
git checkout master .gitignore
mv ./docs/_build/html/* ./
rm -rf ./docs
git add -A
git commit -m "publish updated docs" --no-verify
git push origin gh-pages --force
## switch back
git checkout master
