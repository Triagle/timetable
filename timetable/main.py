""" Print, display, and manage your UC timetable.

Usage:
    timetable [-v] show [--on=<date>] [--drop-cache] [--timeline]
    timetable [-v] week [--on=<date>] [--drop-cache]
    timetable [-v] next [--time] [--drop-cache]

Options:
    -h, --help         Show this screen.
    --on=<date>        Show the timetable for this date.
    --drop-cache       Drop the current data file.
    --time             Show the time to the next class.
    -t, --timeline     Show your timetable in a fancy timeline.
    -v, --verbose      Be more verbose.
"""
import calendar
import itertools
import os
import pathlib
import pickle
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta

from drawille import Canvas

from docopt import docopt
from schema import Or, Schema, SchemaError, Use

from . import config, draw, timetable

COMMAND_MAP = {}

COMMAND_SCHEMA = Schema({
    '--on':
    Or(Use(lambda v: datetime.strptime(v, '%Y-%m-%d')), None),
    '--drop-cache':
    bool,
    '--time':
    bool,
    'next':
    bool,
    'show':
    bool,
    'week':
    bool,
    '--verbose':
    bool,
    '--timeline':
    bool
})


def command(name):
    ''' Declare a command to be used by the argument parser.

    Args:
        name (str): The name of the command.

    Returns:
        function: A function takes one argument callback and appends
                  name: callback to COMMAND_MAP. '''

    def decorator(callback):
        COMMAND_MAP[name] = callback
        return callback

    return decorator


def get_config():
    ''' Get all configuration files/data from the config directory.

    "the config directory" in this context means the path specified by
    the TIMETABLE_CONFIG_PATH environment variable.

    Returns:
        (pathlib.Path, list of courses, dict): The
        path to the configuration directory, the list of courses found in
        the data file there, and the parsed config file. '''
    config_path = pathlib.Path(os.getenv('TIMETABLE_CONFIG_PATH'))
    data_path = config_path / 'data'
    config_file = config_path / 'config'
    data = None
    if data_path.exists():
        with open(data_path, 'rb') as infile:
            data = pickle.load(infile)
    return config_path, data, config.parse_config(config_file)


def print_activity(config_dict, date, course, activity):
    ''' Print an activity.

    Prints an activity in the context of the course it belongs to, the
    current date, and the colours specified by the user.

    Args:
        config_dict (dict): Used to obtain the colour to print the course
                       in.
        date (datetime.datetime): The date to filter locations by.
        course (timetable.Course): The parent course of the activity.
        activity (timetable.Activity): The activity to print. '''
    relevant_location = activity.location_valid_for(date)
    start = activity.start.strftime('%H:%M')
    colour = config.colour_of_course(config_dict, course)
    title = f'{colour.value}{course.title}{config.TermColour.RESET.value}'
    end = activity.end.strftime('%H:%M')
    print(
        f'{start} - {end} :: {title} {activity.name} @ {relevant_location.place}'
    )


def print_timeline(config_dict, date, activities):
    ''' Print out your activities in a fancy timeline.

    See timeline.png for an example of what this looks like.

    Args:
        config_dict (dict): The parsed configuration file
        date (datetime.datetime): The current date (used to find locations).
        activities (list of (Course, Activity)): The activities for the current date. '''
    if len(activities) == 0:
        return
    # Find the longest line (in terms of length on the canvas) of the
    # activities and courses. This is to make the boxes as big as the
    # longest line.
    activities = [(course, activity, activity.location_valid_for(date))
                  for course, activity in activities]
    titles = (course.title for course, _, _ in activities)
    names = (act.name for _, act, _ in activities)
    locations = (location.place for _, _, location in activities)
    box_width = max(
        len(line) for line in itertools.chain(titles, names, locations)) * 4
    # The box height is determined by the number of lines
    # Our box will look like this:
    # title
    #
    # name
    # location
    # end time
    # So that's 5 lines times 5 (the height of the pixel in character
    # terms plus a little padding), 25 pixels height.
    box_height = 25
    # Now we convert our (course, activity) pairs to text and bin our
    # activities based on their start time.
    mapping = OrderedDict()
    for course, activity, location in activities:
        key = activity.start.strftime('%H:%M')
        map_bin = mapping.get(key, [])
        activity_text = f'{course.title}\n\n{activity.name}\n{location.place}\n{activity.end:%H:%M}'
        map_bin.append(activity_text)
        mapping[key] = map_bin

    canvas = Canvas()
    draw.timeline(canvas, 0, 0, box_width, box_height, mapping)
    print(canvas.frame())


def find_day_of_week(date, weekday):
    return date + timedelta(days=weekday - date.weekday())


def print_week_timetable(config_dict, date, courses, selected_activities):
    dates = [
        find_day_of_week(date, day)
        for day in range(calendar.MONDAY, calendar.SATURDAY)
    ]
    day_activities = list(
        itertools.chain(*(
            timetable.activities_on(courses, date, selected_activities)
            for date in dates)))
    if len(day_activities) == 0:
        return
    earliest_time = min(day_activities, key=lambda act: act[1].start)[1].start
    latest_time = max(day_activities, key=lambda act: act[1].end)[1].end
    earliest_time = earliest_time.replace(minute=0, second=0)
    if latest_time.minute + latest_time.second > 0:
        latest_time = (latest_time + timedelta(hours=1)).replace(
            minute=0, second=0)
    rendered_activities = defaultdict(list)
    for course, activity in day_activities:
        hours = activity.end.hour - activity.start.hour
        for hour in range(hours):
            dt = date.replace(hour=activity.start.hour, minute=0, second=0)
            rendered_activities[(activity.day,
                                 (dt + timedelta(hours=hour)).time()
                                 )].append(f'{course.title} {activity.name}')
    rendered_timetable = [[''] + calendar.day_name[:5]]

    hours = latest_time.hour - earliest_time.hour
    for hour in range(hours):
        e_dt = date.replace(hour=earliest_time.hour, minute=0, second=0)
        dt = (e_dt + timedelta(hours=hour)).time()
        row = [dt.strftime('%H:%M')]
        for day in range(len(calendar.day_name) - 2):
            row.append('\n'.join(rendered_activities[(day, dt)]))
        rendered_timetable.append(row)

    canvas = Canvas()
    draw.table(canvas, 0, 0, rendered_timetable)
    print(canvas.frame())


@command('week')
def show_week(config_dict, courses, selected_activities, args):
    date = args['--on'] or datetime.now()
    print(f'Showing timetable for {date:week %U of %Y}')
    print_week_timetable(config_dict, date, courses, selected_activities)


@command('show')
def show_timetable(config_dict, courses, selected_activities, args):
    ''' Show a timetable for a particular date.

    This is the output of the 'show' subcommand.

    Args:
        config_dict (dict): The parsed configuration file.
        courses (list of timetable.Course): A list of the parsed courses.
        selected_activities (dict): A dictionary that determines what
                                    activities are selected by the user.
        args (dict): Additional command line arguments. '''
    date = args['--on'] or datetime.now()
    activities = timetable.activities_on(courses, date, selected_activities)
    day = calendar.day_name[date.weekday()]
    isodate = date.date().isoformat()
    print(f'Showing timetable for {day}, {isodate}')
    if args['--timeline'] is True:
        print_timeline(config_dict, date, activities)
    else:
        for course, activity in activities:
            print_activity(config_dict, date, course, activity)


@command('next')
def show_next(config_dict, courses, selected_activities, args):
    ''' Show a timetable for a particular date.

    This is the output of the 'show' subcommand.

    Args:
        config_dict (dict): The parsed configuration file.
        courses (list of timetable.Course): A list of the parsed courses.
        selected_activities (dict): A dictionary that determines what
                                    activities are selected by the user.
        args (dict): Additional command line arguments. '''
    now = datetime.now()
    activities = timetable.activities_on(courses, now, selected_activities)
    next_activity = next(((course, activity) for course, activity in activities
                          if activity.start > now.time()), None)
    if next_activity is not None and args['--time']:
        course, act = next_activity
        time_dt = now.replace(hour=act.start.hour, minute=act.start.minute)
        delta = time_dt - now
        print(delta)
    elif next_activity is not None:
        course, act = next_activity
        print_activity(config_dict, now, course, act)


def main():
    ''' Main function. '''
    arguments = docopt(__doc__, version='Timetable 0.1.0.')
    try:
        arguments = COMMAND_SCHEMA.validate(arguments)
    except SchemaError:
        exit(__doc__)
    try:
        config_path, data, config_dict = get_config()
    except SchemaError as e:
        if arguments['--verbose']:
            exit(e.code)
        else:
            exit('Failed to parse config.')
    courses = config.get_courses(config_dict)
    if data is None or arguments['--drop-cache']:
        for course in courses:
            course.fetch_activities()
    else:
        courses = data
    selected_activities = config.get_selected_activities(config_dict, courses)
    # Find first callback that docopt believes has been called.
    callback = next(callback for cmd, callback in COMMAND_MAP.items()
                    if arguments[cmd] is True)
    callback(config_dict, courses, selected_activities, arguments)
    with open(config_path / 'data', 'wb') as out:
        pickle.dump(courses, out)


if __name__ == '__main__':
    main()
