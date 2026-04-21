# Contributing

Contributions are welcome. Please open an issue before submitting a pull request so the change can be discussed first. Keep pull requests focused — one feature or fix per PR. All code should pass existing tests (`pytest`) and follow the project's existing code style.

For new input format support, add a sample file in `examples/`, extend the appropriate parser in `tech_spend_command_center/parsers/inputs.py`, update `report/builder.py` if the new data adds a new report section, and include tests covering parsing and rendering. By submitting a pull request you agree to license your contribution under the project's MIT License.
