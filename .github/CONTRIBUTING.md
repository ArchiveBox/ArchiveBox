# Contribution Process

1. Confirm your desired features fit into our bigger project goals [Roadmap](https://github.com/pirate/ArchiveBox/wiki/Roadmap).
2. Open an issue with your planned implementation to discuss
3. Check in with me before starting development to make sure your work wont conflict with or duplicate existing work
4. Setup your dev environment, make some changes, and test using the test input files
5. Commit, push, and submit a PR and wait for review feedback
6. Have patience, don't abandon your PR! We love contributors but we all have day jobs and don't always have time to respond to notifications instantly. If you want a faster response, ping @theSquashSH on twitter or Patreon.

**Useful links:**

- https://github.com/pirate/ArchiveBox/issues
- https://github.com/pirate/ArchiveBox/pulls
- https://github.com/pirate/ArchiveBox/wiki/Roadmap
- https://github.com/pirate/ArchiveBox/wiki/Install#manual-setup

### Development Setup

```bash
git clone https://github.com/pirate/ArchiveBox
cd ArchiveBox
# Ideally do this in a virtualenv
pip install -e '.[dev]'  # or use: pipenv install --dev
```

### Running Tests

```bash
./bin/lint.sh
./bin/test.sh
./bin/build.sh
```

### Getting Help

Open issues on Github or message me https://sweeting.me/#contact.
