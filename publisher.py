import os
import re
import sys
import json
import logging

import gitlab

ISSUE_LABEL = 'auto'

h = logging.StreamHandler(sys.stdout)
h.setFormatter(logging.Formatter(
    '%(levelname)8s %(asctime)s [%(name)12s - %(funcName)20s] %(message)s'))


class Publisher(object):
    def __init__(self, gtlb, config):
        super(Publisher, self).__init__()
        self.gtlb = gtlb
        self.config = config
        self.mr_list = []
        self.logger = logging.getLogger('Publisher')
        self.logger.addHandler(h)
        self.logger.setLevel(logging.INFO)
        self.logger.info("The Publisher object was created.")

    def get_modules(self, gtlb_proj, mod_desc, branch_name):
        return [i for i in gtlb_proj.repository_tree(all=True, ref=branch_name) if re.search(mod_desc, i['path'])]

    def get_files(self, gtlb_proj, mod_path, fil_desc, branch_name):
        return [i for i in gtlb_proj.repository_tree(path=mod_path, recursive=True, all=True, ref=branch_name)
                if i['type'] == 'blob' and re.search(fil_desc, i['path'])]

    def get_all_files(self, gtlb_proj, mod_desc, fil_desc, branch_name):
        # This is to say that when mod name and file name are the same, files under root will be picked up.
        # Note: based on the assumption that no modules like jenkins or gradle will ever exist.
        if mod_desc == fil_desc:
            return [f for f in self.get_modules(gtlb_proj, mod_desc, branch_name)]
        else:
            return [f for mod in self.get_modules(gtlb_proj, mod_desc, branch_name)
                    for f in self.get_files(gtlb_proj, mod['path'], fil_desc, branch_name)]

    def modify_content(self, rawfile, replacements):
        m = rawfile.decode()
        for rep in replacements:
            if rep['append_flag']:
                m = m + rep['new_str']
            else:
                # m = re.sub(rep['old_str'], rep['new_str'], m)
                m = m.replace(rep['old_str'], rep['new_str'])
        return m

    def delete_files_actions(self, gtlb_proj, branch, dsl):
        mods = get_modules(gtlb_proj, dsl['mod_desc'], branch.name)
        delete_files = [{'action': 'delete', 'file_path': f['path']}
                        for mod in mods for f in get_files(gtlb_proj, mod['path'], dsl['fil_desc'], branch.name)]
        return delete_files

    def change_files_actions(self, gtlb_proj, branch, dsl):
        result = []
        for fp in [f['path'] for f in self.get_all_files(gtlb_proj, dsl['mod_desc'], dsl['fil_desc'], branch.name)]:
            self.logger.info(
                'About to access this file path: {} of this branch * {} *'.format(fp, branch.name))
            rawfile = gtlb_proj.files.get(
                file_path=fp, ref=branch.name).decode()
            result.append({
                'action': 'update',
                'file_path': fp,
                'content': self.modify_content(rawfile, dsl['replacements'])
            })
        return result

    def dsl_to_commit_payload(self, gtlb_proj, branch, dsl_list):
        result = []
        for dsl in dsl_list:
            if dsl['type'] == 'update':
                result.extend(self.change_files_actions(
                    gtlb_proj, branch, dsl))
            elif dsl['type'] == 'delete':
                # TODO
                result.extend(self.delete_files_actions(
                    gtlb_proj, branch, dsl))
            elif dsl['type'] == 'create':
                # TODO
                result.extend(self.create_files_actions())
        return result

    def build_up_commit_payload(self, gtlb_proj, branch, dsl):
        result = {}
        result['branch'] = branch.name
        issue_iid = ''.join([s for s in branch.name if s.isdigit()])
        result['commit_message'] = dsl['commit_msg'] + ' #' + issue_iid
        result['actions'] = self.dsl_to_commit_payload(
            gtlb_proj, branch, dsl['changes'])
        return result

    def create_an_issue(self, gtlb_proj):
        auto_issues = gtlb_proj.issues.list(label=ISSUE_LABEL)
        issue_title = self.config['issue_title']
        with open('issue.md', 'r', encoding='utf-8') as issuefile:
            issue_desc = issuefile.read()
        if issue_title not in [i.title for i in auto_issues]:
            issue = gtlb_proj.issues.create({'title': issue_title,
                                             'description': issue_desc,
                                             'labels': [ISSUE_LABEL]})
            self.logger.info('Issue created at {}'.format(issue.web_url))
        else:
            issue = [i for i in auto_issues if i.title == issue_title].pop()
            self.logger.info('Issue found at {}'.format(
                issue.web_url))
            issue.description = issue_desc
            issue.state_event = 'reopen'
            issue.save()
        return issue

    def create_a_branch(self, gtlb_proj, branch_name, main_branch):
        try:
            branch = gtlb_proj.branches.get(branch_name)
            self.logger.info('Branch found at {}'.format(branch.name))
        except gitlab.exceptions.GitlabGetError:
            branch = gtlb_proj.branches.create(
                {'branch': branch_name, 'ref': main_branch})
            self.logger.info('Branch created as {}'.format(branch.name))
        return branch

    def create_an_mr(self, gtlb_proj, branch_name, issue, main_branch):
        mr_title = self.config['issue_title'] + " #" + str(issue.iid)
        current_mrs = gtlb_proj.mergerequests.list()
        if branch_name not in [m.source_branch for m in current_mrs]:
            mr = gtlb_proj.mergerequests.create({'source_branch': branch_name,
                                                 'target_branch': main_branch,
                                                 'title': mr_title,
                                                 'description': '# ATTENTION \n Make sure you have read {} \n close #{}'.format(issue.iid, issue.iid),
                                                 'remove_source_branch': True})
            self.logger.info('MR created at {}'.format(mr.web_url))
        else:
            mr = [m for m in current_mrs if m.source_branch == branch_name][0]
            self.logger.info('MR found at {}'.format(mr.web_url))
        return mr

    def push_changes(self, gtlb_proj, branch, dsl):
        existing_commits = gtlb_proj.commits.list(ref_name=branch.name)
        already_done_flag = [
            x.title for x in existing_commits if x.title.startswith(dsl['commit_msg'])]
        if not already_done_flag:
            data = self.build_up_commit_payload(gtlb_proj, branch, dsl)
            self.logger.info('Pushing commit of {} to branch {}'.format(
                dsl['commit_msg'], branch.name))
            return gtlb_proj.commits.create(data)
        else:
            self.logger.info('The commit was already pushed: {}.'.format(
                dsl['commit_msg']))

    def process_one(self, gtlb_proj_name, main_branch):
        self.logger.info('------ Starting to process ' + gtlb_proj_name)

        gtlb_proj = self.gtlb.projects.get(gtlb_proj_name)

        jenk_hooks = [h for h in gtlb_proj.hooks.list()
                      if 'jenkins' in h.url]
        if jenk_hooks:
            jenk_hook = jenk_hooks.pop()
            # Turn off the hook to avoid too much triggers on a CI server
            jenk_hook.delete()
            self.logger.info(
                '-- Delete the webhook for the moment: {}'.format(jenk_hook.url))

        issue = self.create_an_issue(gtlb_proj)

        branch_name = 'issue_{}_{}'.format(
            issue.iid, self.config['branch_npf'])
        branch = self.create_a_branch(gtlb_proj, branch_name, main_branch)

        mr = self.create_an_mr(gtlb_proj, branch_name, issue, main_branch)
        self.mr_list.append((issue.web_url, mr.web_url))

        for i in range(0, len(self.config['actions'])):
            # Resotre the webhook if this is the last commit
            if (i == len(self.config['actions']) - 1) and jenk_hooks:
                gtlb_proj.hooks.create(
                    {'url': jenk_hook.url, 'push_events': 1, 'merge_requests_events': 1})
                self.logger.info('-- Resotred the webhook')
            dsl = self.config['actions'][i]
            self.logger.info(
                'Processing this dsl: {}'.format(dsl['commit_msg']))
            self.push_changes(gtlb_proj, branch, dsl)
        self.logger.info('------ Finished processing ' + gtlb_proj_name)
        self.logger.info('\n')


def main():
    with open('config.json', encoding="utf-8") as f:
        config = json.load(f)
    gtlb = gitlab.Gitlab(config['gitlab_url'],
                         os.environ['GITLAB_ACCESS_TOKEN'], api_version=4)
    publisher = Publisher(gtlb, config)
    [publisher.process_one(gtlb_proj_name, main_branch)
     for proj in config['proj_list'] for gtlb_proj_name, main_branch in proj.items()]
    # print('\n'.join([i[0] for i in publisher.mr_list]))
    # print('\n'.join([i[1] for i in publisher.mr_list]))


if __name__ == '__main__':
    main()
