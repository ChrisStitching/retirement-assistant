# ToDo

Actionable backlog for planned implementation work.

1. Add an import option to pull in images from personal local storage, extract text from images, and extract location from metadata. Prompt the user for additional details as needed, then create new activities, appointments, and timed events from the imported images.
2. Integrate support for calendars. 
3. Add duration information to each activity. Use the appointments to determine which activities should be in the suggestion pool for the day. For example, if I have an appointment in the afternoon, only short duration activities should be suggested. If I have a morning appointment or a dinner appointment, short and medium duration activities can be in the pool. If the day is free, any duration activity can be selected, but medium or long duration activities should be preferred.
4. The current daily briefing logic is tuned to my weekdays when I focus on solo outings. Weekends are meant to be shared with my spouse, letting him choose the activity. Add weekend logic that proposes activities suitable for shared experiences with him, like bicycling or shared lunch, just in case he doesn't have any ideas.
5. Add seasonality constraints. Certain activities are only available certain months of the year, so should only come up in the daily briefing as options during the appropriate season.
