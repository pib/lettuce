# -*- coding: utf-8 -*-
# <Lettuce - Behaviour Driven Development for python>
# Copyright (C) <2010>  Gabriel Falcão <gabriel@nacaolivre.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
import os
import sys
from optparse import make_option
from django.conf import settings
from django.core.management.base import BaseCommand
from django.test.simple import DjangoTestSuiteRunner
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test.utils import setup_test_environment
from django.test.utils import teardown_test_environment

from lettuce import Runner
from lettuce import registry

from lettuce.django import server
from lettuce.django import harvest_lettuces


class Command(BaseCommand):
    help = u'Run lettuce tests all along installed apps'
    args = '[PATH to feature file or folder]'
    requires_model_validation = False

    option_list = BaseCommand.option_list[1:] + (
        make_option('-v', '--verbosity', action='store', dest='verbosity', default='4',
            type='choice', choices=['0', '3', '4'],
            help='Verbosity level; 0=no output, 3=colorless output, 4=normal output (colorful)'),

        make_option('-a', '--apps', action='store', dest='apps', default='',
            help='Run ONLY the django apps that are listed here. Comma separated'),

        make_option('-A', '--avoid-apps', action='store', dest='avoid_apps', default='',
            help='AVOID running the django apps that are listed here. Comma separated'),

        make_option('-S', '--no-server', action='store_true', dest='no_server', default=False,
            help="will not run django's builtin HTTP server"),

        make_option('-d', '--debug-mode', action='store_true', dest='debug', default=False,
            help="when put together with builtin HTTP server, forces django to run with settings.DEBUG=True"),

        make_option('-s', '--scenarios', action='store', dest='scenarios', default=None,
            help='Comma separated list of scenarios to run'),

        make_option('-t', '--test-database', action='store_true',
                    dest='test_database', default=False,
                    help='Use the test database of Django.'),
    )


    def stopserver(self, failed=False):
        raise SystemExit(int(failed))

    def get_paths(self, args, apps_to_run, apps_to_avoid):
        if args:
            for path, exists in zip(args, map(os.path.exists, args)):
                if not exists:
                    sys.stderr.write("You passed the path '%s', but it does not exist.\n" % path)
                    sys.exit(1)
            else:
                paths = args
        else:
            paths = harvest_lettuces(apps_to_run, apps_to_avoid) # list of tuples with (path, app_module)

        return paths

    def handle(self, *args, **options):
        verbosity = int(options.get('verbosity', 4))
        test_runner = DjangoTestSuiteRunner(verbosity=verbosity)
        test_runner.setup_test_environment()

        settings.DEBUG = options.get('debug', False)
        apps_to_run = tuple(options.get('apps', '').split(","))
        apps_to_avoid = tuple(options.get('avoid_apps', '').split(","))
        run_server = not options.get('no_server', False)

        paths = self.get_paths(args, apps_to_run, apps_to_avoid)
        if run_server:
            server.start()

        os.environ['SERVER_NAME'] = server.address
        os.environ['SERVER_PORT'] = str(server.port)

        failed = False

        registry.call_hook('before', 'harvest', locals())
        results = []
        try:
            try:
                if options.get('test_database'):
                    sys.stdout.write("Setting up a test database...\n")
                    test_db = test_runner.setup_databases()
                    sys.stdout.write("OK\n")

                    if 'south' in settings.INSTALLED_APPS:
                        migrate_options = dict(settings=options['settings'])
                        call_command('migrate', **migrate_options)

            except ImproperlyConfigured, e:
                if "You haven't set the database" in unicode(e):
                    # lettuce will be able to test django projects that
                    # does not have database
                    test_db = None
                else:
                    raise e

            for path in paths:
                app_module = None
                if isinstance(path, tuple) and len(path) is 2:
                    path, app_module = path

                if app_module is not None:
                    registry.call_hook('before_each', 'app', app_module)

                runner = Runner(path, options.get('scenarios'), verbosity)
                result = runner.run()
                if app_module is not None:
                    registry.call_hook('after_each', 'app', app_module, result)

                results.append(result)
                if not result or result.steps != result.steps_passed:
                    failed = True

        except Exception, e:
            import traceback
            traceback.print_exc(e)

        finally:
            registry.call_hook('after', 'harvest', results)

            if options.get('test_database') and test_db:
                sys.stdout.write("Destroying test database...\n")
                test_runner.teardown_databases(test_db)
                sys.stdout.write("OK\n")

            test_runner.teardown_test_environment()
            server.stop(failed)
