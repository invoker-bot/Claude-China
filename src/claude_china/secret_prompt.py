import sys

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.history import DummyHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import BufferControl, Layout, Window
from prompt_toolkit.layout.processors import Processor, Transformation
from prompt_toolkit.output import create_output


class _CharacterCount(Processor):
    def __init__(self, prompt):
        self.prompt = prompt

    def apply_transformation(self, transformation):
        document = transformation.document
        count = len(document.text)
        label = f"{self.prompt}{count} {'char' if count == 1 else 'chars'}"
        return Transformation(
            [("", label + " (Ctrl+U to clear)")],
            source_to_display=lambda _: len(label),
            display_to_source=lambda _: document.cursor_position,
        )


def read_secret(prompt):
    buffer = Buffer(multiline=False, history=DummyHistory())
    keys = KeyBindings()

    @keys.add("enter")
    def submit(event):
        value = buffer.text.strip()
        if "\n" in value or "\r" in value:
            event.app.exit(exception=ValueError("Secret input must contain exactly one line"))
        else:
            event.app.exit(result=value)

    @keys.add("c-u")
    def clear(event):
        buffer.reset()

    @keys.add("c-c")
    @keys.add("<sigint>")
    def cancel(event):
        event.app.exit(exception=KeyboardInterrupt())

    @keys.add("c-d")
    def end_input(event):
        event.app.exit(exception=EOFError())

    control = BufferControl(buffer=buffer, input_processors=[_CharacterCount(prompt)])
    return Application(
        layout=Layout(Window(control, height=1)),
        key_bindings=keys,
        output=create_output(stdout=sys.stderr),
    ).run()
