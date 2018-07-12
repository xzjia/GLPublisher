# What's this

GLPublisher is a small script that can be used to publish a pre-defined set of changes to a list of gitlab projects.
"Publish" here means the following things:

- Create an issue for each project
  - The issue title is defined in `config.json`, and the issue content can be pre-written in `issue.md`
  - If the issue has a same title already exists, GLPublisher won't make a new issue. Instead, it will make sure the issue has the same content with the file.
- Create a branch
  - The branch name has a convention of `issue_{issue_number}_{suffix_defined}`. `issue_number` is from the above step, and `suffix_defined` is defined in `config.json`.
- Create a Merge request from the above created branch.
- Commit changes defined in `config.json`.

# How to set up

You will need to have [pipenv](https://docs.pipenv.org/) to set it up and running.
(For sure you can ignore that and pick up the requirements and install them on your global python. And if you understand what that means, go ahead.)

Make sure you have an environment variable named `GITLAB_ACCESS_TOKEN` that you can get from your Gitlab settings.

```bash
# The paper work: clone the repository and cd into it

$ pipenv install --dev # Install all the dependencies

$ pipenv shell # Spawns a shell within the virtualenv

# Fill in issue.txt and config.json for necessary information

$ pipenv run python publisher.py
```

# Description of `config.json`

TODO
