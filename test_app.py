import unittest

from app import app, init_db


class StudyPlannerAppTests(unittest.TestCase):
    def setUp(self):
        init_db()
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        self.client = app.test_client()

    def login(self, username='tester', password='secret123'):
        self.client.post('/register', data={'username': username, 'password': password}, follow_redirects=True)
        return self.client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)

    def test_home_page_renders_task_form_for_logged_in_user(self):
        self.login()
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Add a new study task', response.data)
        self.assertIn(b'Your tasks', response.data)

    def test_can_create_task_and_navigation_works_for_planner(self):
        self.login()
        self.client.post('/add', data={
            'name': 'Review chemistry notes',
            'due_date': '2026-09-10',
            'duration_value': '45',
            'duration_unit': 'minutes',
            'priority': 'high',
            'notes': 'Flashcards',
        }, follow_redirects=True)

        response = self.client.get('/planner?week_start=2026-09-07')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Review chemistry notes', response.data)
        self.assertIn(b'Prev week', response.data)

    def test_homepage_has_study_timer_option(self):
        self.login()
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Study timer', response.data)


if __name__ == '__main__':
    unittest.main()
