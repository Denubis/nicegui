import asyncio
import time

from nicegui import app, ui
from nicegui.testing import Screen, User


def test_removing_outbox_loops(screen: Screen):
    @ui.page('/')
    def page():
        ui.label('Index page')

    @ui.page('/subpage', reconnect_timeout=0.1)
    def subpage():
        ui.button('Click me', on_click=lambda: ui.notify('Hello world!'))

    state = {'count': 0}
    app.timer(0.1, lambda: state.update(count=len([t for t in asyncio.all_tasks()
                                                   if t.get_name().startswith('outbox loop')])))

    screen.open('/subpage')
    screen.click('Click me')
    screen.should_contain('Hello world!')
    assert state['count'] == 1

    screen.open('/')
    screen.should_contain('Index page')
    screen.wait(0.5)  # wait for the outbox loop to finish
    assert state['count'] == 1


async def test_outbox_stop_wakes_loop(user: User):
    @ui.page('/')
    def page():
        ui.label('Hello')

    await user.open('/')
    client = user.client
    assert client is not None

    outbox_task = None
    for t in asyncio.all_tasks():
        name = t.get_name() or ''
        if not t.done() and name.startswith('outbox loop') and client.id in name:
            outbox_task = t
            break
    assert outbox_task is not None, 'outbox loop task not found'

    # NOTE: in user simulation the loop spins on the has_socket_connection check (sleep 0.1s),
    # never reaching Event.wait(timeout=1.0). Clearing the event forces the loop into the slow
    # path where the bug manifests: stop() sets _should_stop but doesn't wake Event.wait.
    client.outbox._enqueue_event.clear()
    await asyncio.sleep(0.2)  # let loop enter Event.wait

    start = time.monotonic()
    client.outbox.stop()

    while not outbox_task.done() and time.monotonic() - start < 2.0:
        await asyncio.sleep(0.01)
    elapsed = time.monotonic() - start

    assert elapsed < 0.5, f'outbox loop should stop promptly after stop(), took {elapsed:.3f}s'
