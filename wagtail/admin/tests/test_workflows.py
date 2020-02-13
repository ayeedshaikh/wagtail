import logging
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.test import TestCase, override_settings
from django.urls import reverse

from wagtail.core.models import (
    GroupApprovalTask, Page, Task, TaskState, Workflow, WorkflowPage, WorkflowState, WorkflowTask)
from wagtail.core.signals import page_published
from wagtail.tests.testapp.models import SimplePage, SimpleTask
from wagtail.tests.utils import WagtailTestUtils
from wagtail.users.models import UserProfile


class TestWorkflowsIndexView(TestCase, WagtailTestUtils):

    def setUp(self):
        self.login()

    def get(self, params={}):
        return self.client.get(reverse('wagtailadmin_workflows:index'), params)

    def test_simple(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'wagtailadmin/workflows/index.html')

        # Initially there should be no workflows listed
        self.assertContains(response, "There are no enabled workflows.")

        Workflow.objects.create(name="test_workflow", active=True)

        # Now the listing should contain our workflow
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'wagtailadmin/workflows/index.html')
        self.assertNotContains(response, "There are no enabled workflows.")
        self.assertContains(response, "test_workflow")

    def test_deactivated(self):
        Workflow.objects.create(name="test_workflow", active=False)

        # The listing should contain our workflow, as well as marking it as disabled
        response = self.get(params={'show_disabled': 'True'})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "No workflows have been created.")
        self.assertContains(response, "test_workflow")
        self.assertContains(response, '<span class="status-tag">Disabled</span>', html=True)

        # If we set 'show_disabled' to 'False', the workflow should not be displayed
        response = self.get(params={'show_disabled': 'False'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "There are no enabled workflows.")


class TestWorkflowsCreateView(TestCase, WagtailTestUtils):

    def setUp(self):
        self.login()
        self.task_1 = SimpleTask.objects.create(name="first_task")
        self.task_2 = SimpleTask.objects.create(name="second_task")


    def get(self, params={}):
        return self.client.get(reverse('wagtailadmin_workflows:add'), params)

    def post(self, post_data={}):
        return self.client.post(reverse('wagtailadmin_workflows:add'), post_data)

    def test_get(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'wagtailadmin/workflows/create.html')

    def test_post(self):
        response = self.post({
            'name': ['test_workflow'], 'active': ['on'], 'workflow_tasks-TOTAL_FORMS': ['2'],
            'workflow_tasks-INITIAL_FORMS': ['0'], 'workflow_tasks-MIN_NUM_FORMS': ['0'],
            'workflow_tasks-MAX_NUM_FORMS': ['1000'], 'workflow_tasks-0-task': [str(self.task_1.id)], 'workflow_tasks-0-id': [''],
            'workflow_tasks-0-ORDER': ['1'], 'workflow_tasks-0-DELETE': [''], 'workflow_tasks-1-task': [str(self.task_2.id)],
            'workflow_tasks-1-id': [''], 'workflow_tasks-1-ORDER': ['2'], 'workflow_tasks-1-DELETE': ['']})


        # Should redirect back to index
        self.assertRedirects(response, reverse('wagtailadmin_workflows:index'))

        # Check that the workflow was created
        workflows = Workflow.objects.filter(name="test_workflow", active=True)
        self.assertEqual(workflows.count(), 1)

        workflow = workflows.first()

        # Check that the tasks are associated with the workflow
        self.assertEqual([self.task_1.task_ptr, self.task_2.task_ptr], list(workflow.tasks))

        # Check that the tasks have sort_order set on WorkflowTask correctly
        self.assertEqual(WorkflowTask.objects.get(workflow=workflow, task=self.task_1.task_ptr).sort_order, 0)
        self.assertEqual(WorkflowTask.objects.get(workflow=workflow, task=self.task_2.task_ptr).sort_order, 1)


class TestWorkflowsEditView(TestCase, WagtailTestUtils):

    def setUp(self):
        self.login()
        self.workflow = Workflow.objects.create(name="workflow_to_edit")
        self.task_1 = SimpleTask.objects.create(name="first_task")
        self.task_2 = SimpleTask.objects.create(name="second_task")
        self.inactive_task = SimpleTask.objects.create(name="inactive_task", active=False)
        self.workflow_task = WorkflowTask.objects.create(workflow=self.workflow, task=self.task_1.task_ptr, sort_order=0)
        self.page = Page.objects.first()
        WorkflowPage.objects.create(workflow=self.workflow, page=self.page)


    def get(self, params={}):
        return self.client.get(reverse('wagtailadmin_workflows:edit', args=[self.workflow.id]), params)

    def post(self, post_data={}):
        return self.client.post(reverse('wagtailadmin_workflows:edit', args=[self.workflow.id]), post_data)

    def test_get(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'wagtailadmin/workflows/edit.html')

        # Test that the form contains options for the active tasks, but not the inactive task
        self.assertContains(response, "first_task")
        self.assertContains(response, "second_task")
        self.assertNotContains(response, "inactive_task")

        # Check that the list of pages has the page to which this workflow is assigned
        self.assertContains(response, self.page.title)

    def test_post(self):
        response = self.post({
            'name': [str(self.workflow.name)],
            'active': ['on'],
            'workflow_tasks-TOTAL_FORMS': ['2'],
            'workflow_tasks-INITIAL_FORMS': ['1'],
            'workflow_tasks-MIN_NUM_FORMS': ['0'],
            'workflow_tasks-MAX_NUM_FORMS': ['1000'],
            'workflow_tasks-0-task': [str(self.task_1.id)],
            'workflow_tasks-0-id': [str(self.workflow_task.id)],
            'workflow_tasks-0-ORDER': ['1'],
            'workflow_tasks-0-DELETE': [''],
            'workflow_tasks-1-task': [str(self.task_2.id)],
            'workflow_tasks-1-id': [''],
            'workflow_tasks-1-ORDER': ['2'],
            'workflow_tasks-1-DELETE': ['']})


        # Should redirect back to index
        self.assertRedirects(response, reverse('wagtailadmin_workflows:index'))

        # Check that the workflow was created
        workflows = Workflow.objects.filter(name="workflow_to_edit", active=True)
        self.assertEqual(workflows.count(), 1)

        workflow = workflows.first()

        # Check that the tasks are associated with the workflow
        self.assertEqual([self.task_1.task_ptr, self.task_2.task_ptr], list(workflow.tasks))

        # Check that the tasks have sort_order set on WorkflowTask correctly
        self.assertEqual(WorkflowTask.objects.get(workflow=workflow, task=self.task_1.task_ptr).sort_order, 0)
        self.assertEqual(WorkflowTask.objects.get(workflow=workflow, task=self.task_2.task_ptr).sort_order, 1)


class TestAddWorkflowToPage(TestCase, WagtailTestUtils):
    fixtures = ['test.json']

    def setUp(self):
        self.login()
        self.workflow = Workflow.objects.create(name="workflow")
        self.page = Page.objects.first()
        self.other_workflow = Workflow.objects.create(name="other_workflow")
        self.other_page = Page.objects.last()
        WorkflowPage.objects.create(workflow=self.other_workflow, page=self.other_page)

    def get(self, params={}):
        return self.client.get(reverse('wagtailadmin_workflows:add_to_page', args=[self.workflow.id]), params)

    def post(self, post_data={}):
        return self.client.post(reverse('wagtailadmin_workflows:add_to_page', args=[self.workflow.id]), post_data)

    def test_get(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'wagtailadmin/workflows/add_to_page.html')

    def test_post(self):
        # Check that a WorkflowPage instance is created correctly when a page with no existing workflow is created
        self.post({'page': str(self.page.id), 'workflow': str(self.workflow.id)})
        self.assertEqual(WorkflowPage.objects.filter(workflow=self.workflow, page=self.page).count(), 1)

        # Check that trying to add a WorkflowPage for a page with an existing workflow does not create
        self.post({'page': str(self.other_page.id), 'workflow': str(self.workflow.id)})
        self.assertEqual(WorkflowPage.objects.filter(workflow=self.workflow, page=self.other_page).count(), 0)

        # Check that this can be overridden by setting overwrite_existing to true
        self.post({'page': str(self.other_page.id), 'overwrite_existing': 'True', 'workflow': str(self.workflow.id)})
        self.assertEqual(WorkflowPage.objects.filter(workflow=self.workflow, page=self.other_page).count(), 1)


class TestRemoveWorkflow(TestCase, WagtailTestUtils):
    fixtures = ['test.json']

    def setUp(self):
        self.login()
        self.workflow = Workflow.objects.create(name="workflow")
        self.page = Page.objects.first()
        WorkflowPage.objects.create(workflow=self.workflow, page=self.page)

    def post(self, post_data={}):
        return self.client.post(reverse('wagtailadmin_workflows:remove', args=[self.workflow.id, self.page.id]), post_data)

    def test_post(self):
        # Check that a WorkflowPage instance is removed correctly
        self.post()
        self.assertEqual(WorkflowPage.objects.filter(workflow=self.workflow, page=self.page).count(), 0)


class TestTaskIndexView(TestCase, WagtailTestUtils):

    def setUp(self):
        self.login()

    def get(self, params={}):
        return self.client.get(reverse('wagtailadmin_workflows:task_index'), params)

    def test_simple(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'wagtailadmin/workflows/task_index.html')

        # Initially there should be no tasks listed
        self.assertContains(response, "There are no enabled tasks")

        SimpleTask.objects.create(name="test_task", active=True)

        # Now the listing should contain our task
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'wagtailadmin/workflows/task_index.html')
        self.assertNotContains(response, "There are no enabled tasks")
        self.assertContains(response, "test_task")

    def test_deactivated(self):
        Task.objects.create(name="test_task", active=False)

        # The listing should contain our task, as well as marking it as disabled
        response = self.get(params={'show_disabled': 'True'})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "No tasks have been created.")
        self.assertContains(response, "test_task")
        self.assertContains(response, '<span class="status-tag">Disabled</span>', html=True)

        # The listing should not contain task if show_disabled query parameter is 'False'
        response = self.get(params={'show_disabled': 'False'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "There are no enabled tasks")
        self.assertNotContains(response, "test_task")


class TestCreateTaskView(TestCase, WagtailTestUtils):

    def setUp(self):
        self.login()

    def get(self, params={}):
        return self.client.get(reverse('wagtailadmin_workflows:add_task', kwargs={'app_label': SimpleTask._meta.app_label, 'model_name': SimpleTask._meta.model_name}), params)

    def post(self, post_data={}):
        return self.client.post(reverse('wagtailadmin_workflows:add_task', kwargs={'app_label': SimpleTask._meta.app_label, 'model_name': SimpleTask._meta.model_name}), post_data)

    def test_get(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'wagtailadmin/workflows/create_task.html')

    def test_post(self):
        response = self.post({'name': 'test_task', 'active': 'on'})

        # Should redirect back to index
        self.assertRedirects(response, reverse('wagtailadmin_workflows:task_index'))

        # Check that the task was created
        tasks = Task.objects.filter(name="test_task", active=True)
        self.assertEqual(tasks.count(), 1)


class TestSelectTaskTypeView(TestCase, WagtailTestUtils):

    def setUp(self):
        self.login()

    def get(self):
        return self.client.get(reverse('wagtailadmin_workflows:select_task_type'))

    def test_get(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'wagtailadmin/workflows/select_task_type.html')

        # Check that the list of available task types includes SimpleTask and GroupApprovalTask
        self.assertContains(response, SimpleTask.get_verbose_name())
        self.assertContains(response, GroupApprovalTask.get_verbose_name())


class TestEditTaskView(TestCase, WagtailTestUtils):

    def setUp(self):
        self.login()
        self.task = SimpleTask.objects.create(name="test_task")

    def get(self, params={}):
        return self.client.get(reverse('wagtailadmin_workflows:edit_task', args=[self.task.id]), params)

    def post(self, post_data={}):
        return self.client.post(reverse('wagtailadmin_workflows:edit_task', args=[self.task.id]), post_data)

    def test_get(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'wagtailadmin/workflows/edit_task.html')

    def test_post(self):
        response = self.post({'name': 'test_task_modified', 'active': 'on'})

        # Should redirect back to index
        self.assertRedirects(response, reverse('wagtailadmin_workflows:task_index'))

        # Check that the task was updated
        task = Task.objects.get(id=self.task.id)
        self.assertEqual(task.name, "test_task_modified")


class TestSubmitToWorkflow(TestCase, WagtailTestUtils):
    def setUp(self):
        self.submitter = get_user_model().objects.create_user(
            username='submitter',
            email='submitter@email.com',
            password='password',
        )
        editors = Group.objects.get(name='Editors')
        editors.user_set.add(self.submitter)
        self.moderator = get_user_model().objects.create_user(
            username='moderator',
            email='moderator@email.com',
            password='password',
        )
        moderators = Group.objects.get(name='Moderators')
        moderators.user_set.add(self.moderator)

        self.superuser = get_user_model().objects.create_superuser(
            username='superuser',
            email='superuser@email.com',
            password='password',
        )

        self.login(user=self.submitter)

        # Create a page
        root_page = Page.objects.get(id=2)
        self.page = SimplePage(
            title="Hello world!",
            slug='hello-world',
            content="hello",
            live=False,
            has_unpublished_changes=True,
        )
        root_page.add_child(instance=self.page)

        self.workflow, self.task_1 = self.create_workflow_and_tasks()

        WorkflowPage.objects.create(workflow=self.workflow, page=self.page)

    def create_workflow_and_tasks(self):
        workflow = Workflow.objects.create(name='test_workflow')
        task_1 = GroupApprovalTask.objects.create(name='test_task_1', group=Group.objects.get(name='Moderators'))
        WorkflowTask.objects.create(workflow=workflow, task=task_1, sort_order=1)
        return workflow, task_1

    def submit(self):
        post_data = {
            'title': str(self.page.title),
            'slug': str(self.page.slug),
            'content': str(self.page.content),
            'action-submit': "True",
        }
        return self.client.post(reverse('wagtailadmin_pages:edit', args=(self.page.id,)), post_data)

    def test_submit_for_approval_creates_states(self):
        """Test that WorkflowState and TaskState objects are correctly created when a Page is submitted for approval"""

        self.submit()

        workflow_state = self.page.current_workflow_state

        self.assertEqual(type(workflow_state), WorkflowState)
        self.assertEqual(workflow_state.workflow, self.workflow)
        self.assertEqual(workflow_state.status, workflow_state.STATUS_IN_PROGRESS)
        self.assertEqual(workflow_state.requested_by, self.submitter)

        task_state = workflow_state.current_task_state

        self.assertEqual(type(task_state), TaskState)
        self.assertEqual(task_state.task.specific, self.task_1)
        self.assertEqual(task_state.status, task_state.STATUS_IN_PROGRESS)

    @mock.patch.object(EmailMultiAlternatives, 'send', side_effect=IOError('Server down'))
    def test_email_send_error(self, mock_fn):
        logging.disable(logging.CRITICAL)

        response = self.submit()
        logging.disable(logging.NOTSET)

        # An email that fails to send should return a message rather than crash the page
        self.assertEqual(response.status_code, 302)
        response = self.client.get(reverse('wagtailadmin_home'))


    def test_email_headers(self):
        # Submit
        self.submit()

        msg_headers = set(mail.outbox[0].message().items())
        headers = {('Auto-Submitted', 'auto-generated')}
        self.assertTrue(headers.issubset(msg_headers), msg='Message is missing the Auto-Submitted header.',)


class TestApproveRejectWorkflow(TestCase, WagtailTestUtils):
    def setUp(self):
        self.submitter = get_user_model().objects.create_user(
            username='submitter',
            email='submitter@email.com',
            password='password',
        )
        editors = Group.objects.get(name='Editors')
        editors.user_set.add(self.submitter)
        self.moderator = get_user_model().objects.create_user(
            username='moderator',
            email='moderator@email.com',
            password='password',
        )
        moderators = Group.objects.get(name='Moderators')
        moderators.user_set.add(self.moderator)

        self.superuser = get_user_model().objects.create_superuser(
            username='superuser',
            email='superuser@email.com',
            password='password',
        )

        self.login(user=self.submitter)

        # Create a page
        root_page = Page.objects.get(id=2)
        self.page = SimplePage(
            title="Hello world!",
            slug='hello-world',
            content="hello",
            live=False,
            has_unpublished_changes=True,
        )
        root_page.add_child(instance=self.page)

        self.workflow, self.task_1 = self.create_workflow_and_tasks()

        WorkflowPage.objects.create(workflow=self.workflow, page=self.page)

        self.submit()

        self.login(user=self.moderator)

    def create_workflow_and_tasks(self):
        workflow = Workflow.objects.create(name='test_workflow')
        task_1 = GroupApprovalTask.objects.create(name='test_task_1', group=Group.objects.get(name='Moderators'))
        WorkflowTask.objects.create(workflow=workflow, task=task_1, sort_order=1)
        return workflow, task_1

    def submit(self):
        post_data = {
            'title': str(self.page.title),
            'slug': str(self.page.slug),
            'content': str(self.page.content),
            'action-submit': "True",
        }
        return self.client.post(reverse('wagtailadmin_pages:edit', args=(self.page.id,)), post_data)

    @override_settings(WAGTAIL_FINISH_WORKFLOW_ACTION='')
    def test_approve_task_and_workflow(self):
        """
        This posts to the approve task view and checks that the page was approved and published
        """
        # Unset WAGTAIL_FINISH_WORKFLOW_ACTION - default action should be to publish
        del settings.WAGTAIL_FINISH_WORKFLOW_ACTION
        # Connect a mock signal handler to page_published signal
        mock_handler = mock.MagicMock()
        page_published.connect(mock_handler)

        # Post
        self.client.post(reverse('wagtailadmin_pages:workflow_action', args=(self.page.id, )), {'action': 'approve'})

        # Check that the workflow was approved

        workflow_state = WorkflowState.objects.get(page=self.page, requested_by=self.submitter)

        self.assertEqual(workflow_state.status, workflow_state.STATUS_APPROVED)

        # Check that the task was approved

        task_state = workflow_state.current_task_state

        self.assertEqual(task_state.status, task_state.STATUS_APPROVED)

        page = Page.objects.get(id=self.page.id)
        # Page must be live
        self.assertTrue(page.live, "Approving moderation failed to set live=True")
        # Page should now have no unpublished changes
        self.assertFalse(
            page.has_unpublished_changes,
            "Approving moderation failed to set has_unpublished_changes=False"
        )

        # Check that the page_published signal was fired
        self.assertEqual(mock_handler.call_count, 1)
        mock_call = mock_handler.mock_calls[0][2]

        self.assertEqual(mock_call['sender'], self.page.specific_class)
        self.assertEqual(mock_call['instance'], self.page)
        self.assertIsInstance(mock_call['instance'], self.page.specific_class)

    def test_workflow_action_view_bad_page_id(self):
        """
        This tests that the workflow action view handles invalid page ids correctly
        """
        # Post
        response = self.client.post(reverse('wagtailadmin_pages:workflow_action', args=(124567, )), {'action': 'approve'})

        # Check that the user received a 404 response
        self.assertEqual(response.status_code, 404)

    def test_workflow_action_view_not_in_group(self):
        """
        This tests that the workflow action view for a GroupApprovalTask won't allow approval from a user not in the
        specified group/a superuser
        """
        # Remove privileges from user
        self.login(user=self.submitter)

        # Post
        response = self.client.post(reverse('wagtailadmin_pages:workflow_action', args=(self.page.id, )), {'action': 'approve'})

        # Check that the user received a 403 response
        self.assertEqual(response.status_code, 403)

    def test_reject_task_and_workflow(self):
        """
        This posts to the reject task view and checks that the page was rejected and not published
        """
        # Post
        self.client.post(reverse('wagtailadmin_pages:workflow_action', args=(self.page.id, )), {'action': 'reject'})

        # Check that the workflow was rejected

        workflow_state = WorkflowState.objects.get(page=self.page, requested_by=self.submitter)

        self.assertEqual(workflow_state.status, workflow_state.STATUS_REJECTED)

        # Check that the task was rejected

        task_state = workflow_state.current_task_state

        self.assertEqual(task_state.status, task_state.STATUS_REJECTED)

        page = Page.objects.get(id=self.page.id)
        # Page must not be live
        self.assertFalse(page.live)


    def test_workflow_action_view_rejection_not_in_group(self):
        """
        This tests that the workflow action view for a GroupApprovalTask won't allow rejection from a user not in the
        specified group/a superuser
        """
        # Remove privileges from user
        self.login(user=self.submitter)

        # Post
        response = self.client.post(reverse('wagtailadmin_pages:workflow_action', args=(self.page.id, )), {'action': 'reject'})

        # Check that the user received a 403 response
        self.assertEqual(response.status_code, 403)


class TestNotificationPreferences(TestCase, WagtailTestUtils):
    def setUp(self):
        self.submitter = get_user_model().objects.create_user(
            username='submitter',
            email='submitter@email.com',
            password='password',
        )
        editors = Group.objects.get(name='Editors')
        editors.user_set.add(self.submitter)
        self.moderator = get_user_model().objects.create_user(
            username='moderator',
            email='moderator@email.com',
            password='password',
        )
        self.moderator2 = get_user_model().objects.create_user(
            username='moderator2',
            email='moderator2@email.com',
            password='password',
        )
        moderators = Group.objects.get(name='Moderators')
        moderators.user_set.add(self.moderator)
        moderators.user_set.add(self.moderator2)

        self.superuser = get_user_model().objects.create_superuser(
            username='superuser',
            email='superuser@email.com',
            password='password',
        )

        self.superuser_profile = UserProfile.get_for_user(self.superuser)
        self.moderator2_profile = UserProfile.get_for_user(self.moderator2)
        self.submitter_profile = UserProfile.get_for_user(self.submitter)

        # Create a page
        root_page = Page.objects.get(id=2)
        self.page = SimplePage(
            title="Hello world!",
            slug='hello-world',
            content="hello",
            live=False,
            has_unpublished_changes=True,
        )
        root_page.add_child(instance=self.page)

        self.workflow, self.task_1 = self.create_workflow_and_tasks()

        WorkflowPage.objects.create(workflow=self.workflow, page=self.page)

    def create_workflow_and_tasks(self):
        workflow = Workflow.objects.create(name='test_workflow')
        task_1 = GroupApprovalTask.objects.create(name='test_task_1', group=Group.objects.get(name='Moderators'))
        WorkflowTask.objects.create(workflow=workflow, task=task_1, sort_order=1)
        return workflow, task_1

    def submit(self):
        post_data = {
            'title': str(self.page.title),
            'slug': str(self.page.slug),
            'content': str(self.page.content),
            'action-submit': "True",
        }
        return self.client.post(reverse('wagtailadmin_pages:edit', args=(self.page.id,)), post_data)

    def approve(self):
        return self.client.post(reverse('wagtailadmin_pages:workflow_action', args=(self.page.id, )), {'action': 'approve'})

    def reject(self):
        return self.client.post(reverse('wagtailadmin_pages:workflow_action', args=(self.page.id, )), {'action': 'reject'})

    def test_vanilla_profile(self):
        # Check that the vanilla profile has rejected notifications on
        self.assertEqual(self.submitter_profile.rejected_notifications, True)

        # Check that the vanilla profile has approved notifications on
        self.assertEqual(self.submitter_profile.approved_notifications, True)

    @override_settings(WAGTAILADMIN_NOTIFICATION_INCLUDE_SUPERUSERS=True)
    def test_submitted_email_notifications_sent(self):
        """Test that 'submitted' notifications for WorkflowState and TaskState are both sent correctly"""
        self.login(self.submitter)
        self.submit()

        self.assertEqual(len(mail.outbox), 4)

        task_submission_emails = [email for email in mail.outbox if "task" in email.subject]
        task_submission_emailed_addresses = [address for email in task_submission_emails for address in email.to]
        workflow_submission_emails = [email for email in mail.outbox if "workflow" in email.subject]
        workflow_submission_emailed_addresses = [address for email in workflow_submission_emails for address in email.to]

        self.assertEqual(len(task_submission_emails), 3)
        # the moderator is in the Group assigned to the GroupApproval task, so should get an email
        self.assertIn(self.moderator.email, task_submission_emailed_addresses)
        self.assertIn(self.moderator2.email, task_submission_emailed_addresses)
        # with `WAGTAILADMIN_NOTIFICATION_INCLUDE_SUPERUSERS`, the superuser should get a task email
        self.assertIn(self.superuser.email, task_submission_emailed_addresses)
        # the submitter triggered this workflow update, so should not get an email
        self.assertNotIn(self.submitter.email, task_submission_emailed_addresses)

        self.assertEqual(len(workflow_submission_emails), 1)
        # the moderator should not get a workflow email
        self.assertNotIn(self.moderator.email, workflow_submission_emailed_addresses)
        self.assertNotIn(self.moderator2.email, workflow_submission_emailed_addresses)
        # with `WAGTAILADMIN_NOTIFICATION_INCLUDE_SUPERUSERS`, the superuser should get a workflow email
        self.assertIn(self.superuser.email, workflow_submission_emailed_addresses)
        # as the submitter was the triggering user, the submitter should not get an email notification
        self.assertNotIn(self.submitter.email, workflow_submission_emailed_addresses)

    @override_settings(WAGTAILADMIN_NOTIFICATION_INCLUDE_SUPERUSERS=False)
    def test_submitted_email_notifications_superuser_settings(self):
        """Test that 'submitted' notifications for WorkflowState and TaskState are not sent to superusers if
        `WAGTAILADMIN_NOTIFICATION_INCLUDE_SUPERUSERS=False`"""
        self.login(self.submitter)
        self.submit()

        task_submission_emails = [email for email in mail.outbox if "task" in email.subject]
        task_submission_emailed_addresses = [address for email in task_submission_emails for address in email.to]
        workflow_submission_emails = [email for email in mail.outbox if "workflow" in email.subject]
        workflow_submission_emailed_addresses = [address for email in workflow_submission_emails for address in email.to]

        # with `WAGTAILADMIN_NOTIFICATION_INCLUDE_SUPERUSERS` off, the superuser should not get a task email
        self.assertNotIn(self.superuser.email, task_submission_emailed_addresses)

        # with `WAGTAILADMIN_NOTIFICATION_INCLUDE_SUPERUSERS` off, the superuser should not get a workflow email
        self.assertNotIn(self.superuser.email, workflow_submission_emailed_addresses)

    @override_settings(WAGTAILADMIN_NOTIFICATION_INCLUDE_SUPERUSERS=True)
    def test_submit_notification_preferences_respected(self):
        # moderator2 doesn't want emails
        self.moderator2_profile.submitted_notifications = False
        self.moderator2_profile.save()

        # superuser doesn't want emails
        self.superuser_profile.submitted_notifications = False
        self.superuser_profile.save()

        # Submit
        self.login(self.submitter)
        self.submit()

        # Check that only one moderator got a task submitted email
        workflow_submission_emails = [email for email in mail.outbox if "workflow" in email.subject]
        workflow_submission_emailed_addresses = [address for email in workflow_submission_emails for address in email.to]
        task_submission_emails = [email for email in mail.outbox if "task" in email.subject]
        task_submission_emailed_addresses = [address for email in task_submission_emails for address in email.to]
        self.assertNotIn(self.moderator2.email, task_submission_emailed_addresses)

        # Check that the superuser didn't receive a workflow or task email
        self.assertNotIn(self.superuser.email, task_submission_emailed_addresses)
        self.assertNotIn(self.superuser.email, workflow_submission_emailed_addresses)

    def test_approved_notifications(self):
        self.login(self.submitter)
        self.submit()
        # Approve
        self.login(self.moderator)
        self.approve()

        # Submitter must receive a workflow approved email
        workflow_approved_emails = [email for email in mail.outbox if ("workflow" in email.subject and "approved" in email.subject)]
        self.assertEqual(len(workflow_approved_emails), 1)
        self.assertIn(self.submitter.email, workflow_approved_emails[0].to)

    def test_approved_notifications_preferences_respected(self):
        # Submitter doesn't want 'approved' emails
        self.submitter_profile.approved_notifications = False
        self.submitter_profile.save()

        self.login(self.submitter)
        self.submit()
        # Approve
        self.login(self.moderator)
        self.approve()

        # Submitter must not receive a workflow approved email, so there should be no emails in workflow_approved_emails
        workflow_approved_emails = [email for email in mail.outbox if ("workflow" in email.subject and "approved" in email.subject)]
        self.assertEqual(len(workflow_approved_emails), 0)

    def test_rejected_notifications(self):
        self.login(self.submitter)
        self.submit()
        # Reject
        self.login(self.moderator)
        self.reject()

        # Submitter must receive a workflow rejected email
        workflow_rejected_emails = [email for email in mail.outbox if ("workflow" in email.subject and "rejected" in email.subject)]
        self.assertEqual(len(workflow_rejected_emails), 1)
        self.assertIn(self.submitter.email, workflow_rejected_emails[0].to)

    def test_rejected_notification_preferences_respected(self):
        # Submitter doesn't want 'rejected' emails
        self.submitter_profile.rejected_notifications = False
        self.submitter_profile.save()

        self.login(self.submitter)
        self.submit()
        # Reject
        self.login(self.moderator)
        self.reject()

        # Submitter must not receive a workflow rejected email
        workflow_rejected_emails = [email for email in mail.outbox if ("workflow" in email.subject and "rejected" in email.subject)]
        self.assertEqual(len(workflow_rejected_emails), 0)


class TestDisableViews(TestCase, WagtailTestUtils):
    def setUp(self):
        self.submitter = get_user_model().objects.create_user(
            username='submitter',
            email='submitter@email.com',
            password='password',
        )
        editors = Group.objects.get(name='Editors')
        editors.user_set.add(self.submitter)
        self.moderator = get_user_model().objects.create_user(
            username='moderator',
            email='moderator@email.com',
            password='password',
        )
        self.moderator2 = get_user_model().objects.create_user(
            username='moderator2',
            email='moderator2@email.com',
            password='password',
        )
        moderators = Group.objects.get(name='Moderators')
        moderators.user_set.add(self.moderator)
        moderators.user_set.add(self.moderator2)

        self.superuser = get_user_model().objects.create_superuser(
            username='superuser',
            email='superuser@email.com',
            password='password',
        )

        # Create a page
        root_page = Page.objects.get(id=2)
        self.page = SimplePage(
            title="Hello world!",
            slug='hello-world',
            content="hello",
            live=False,
            has_unpublished_changes=True,
        )
        root_page.add_child(instance=self.page)

        self.workflow, self.task_1, self.task_2 = self.create_workflow_and_tasks()

        WorkflowPage.objects.create(workflow=self.workflow, page=self.page)

    def create_workflow_and_tasks(self):
        workflow = Workflow.objects.create(name='test_workflow')
        task_1 = GroupApprovalTask.objects.create(name='test_task_1', group=Group.objects.get(name='Moderators'))
        task_2 = GroupApprovalTask.objects.create(name='test_task_2', group=Group.objects.get(name='Moderators'))
        WorkflowTask.objects.create(workflow=workflow, task=task_1, sort_order=1)
        WorkflowTask.objects.create(workflow=workflow, task=task_2, sort_order=2)
        return workflow, task_1, task_2

    def submit(self):
        post_data = {
            'title': str(self.page.title),
            'slug': str(self.page.slug),
            'content': str(self.page.content),
            'action-submit': "True",
        }
        return self.client.post(reverse('wagtailadmin_pages:edit', args=(self.page.id,)), post_data)

    def approve(self):
        return self.client.post(reverse('wagtailadmin_pages:workflow_action', args=(self.page.id, )), {'action': 'approve'})

    def test_disable_workflow(self):
        """Test that deactivating a workflow sets it to inactive and cancels in progress states"""
        self.login(self.submitter)
        self.submit()
        self.login(self.superuser)
        self.approve()

        response = self.client.post(reverse('wagtailadmin_workflows:disable', args=(self.workflow.pk,)))
        self.assertEqual(response.status_code, 302)
        self.workflow.refresh_from_db()
        self.assertEqual(self.workflow.active, False)
        states = WorkflowState.objects.filter(page=self.page, workflow=self.workflow)
        self.assertEqual(states.filter(status=WorkflowState.STATUS_IN_PROGRESS).count(), 0)
        self.assertEqual(states.filter(status=WorkflowState.STATUS_CANCELLED).count(), 1)

    def test_disable_task(self):
        """Test that deactivating a task sets it to inactive and cancels in progress states"""
        self.login(self.submitter)
        self.submit()
        self.login(self.superuser)

        response = self.client.post(reverse('wagtailadmin_workflows:disable_task', args=(self.task_1.pk,)))
        self.assertEqual(response.status_code, 302)
        self.task_1.refresh_from_db()
        self.assertEqual(self.task_1.active, False)
        states = TaskState.objects.filter(workflow_state__page=self.page, task=self.task_1.task_ptr)
        self.assertEqual(states.filter(status=TaskState.STATUS_IN_PROGRESS).count(), 0)
        self.assertEqual(states.filter(status=TaskState.STATUS_CANCELLED).count(), 1)

        # Check that the page's WorkflowState has moved on to the next active task
        self.assertEqual(self.page.current_workflow_state.current_task_state.task.specific, self.task_2)

    def test_enable_workflow(self):
        self.login(self.superuser)
        self.workflow.active = False
        self.workflow.save()

        response = self.client.post(reverse('wagtailadmin_workflows:enable', args=(self.workflow.pk,)))
        self.assertEqual(response.status_code, 302)
        self.workflow.refresh_from_db()
        self.assertEqual(self.workflow.active, True)

    def test_enable_task(self):
        self.login(self.superuser)
        self.task_1.active = False
        self.task_1.save()

        response = self.client.post(reverse('wagtailadmin_workflows:enable_task', args=(self.task_1.pk,)))
        self.assertEqual(response.status_code, 302)
        self.task_1.refresh_from_db()
        self.assertEqual(self.task_1.active, True)