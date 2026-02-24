"""Keyboard-to-hardware input simulator (placeholder).

This module will map keyboard and mouse events from pygame to the same abstract
hardware-button and rotary-encoder events produced by the GPIO backend on the
Raspberry Pi. It is used during Mac development so that the application can be
driven entirely from the keyboard without any physical hardware attached.

Planned key mappings (subject to change):
    F1          -> CHARGE event
    F2          -> FIRST_CRACK event
    F3          -> SECOND_CRACK event
    F4          -> DROP event
    Up arrow    -> BURNER_UP (increase heater power)
    Down arrow  -> BURNER_DOWN (decrease heater power)
    Left arrow  -> AIR_DOWN (decrease fan speed)
    Right arrow -> AIR_UP (increase fan speed)
    +           -> DRUM_UP (increase drum speed)
    -           -> DRUM_DOWN (decrease drum speed)
    M           -> MODE_TOGGLE (switch between manual and auto-PID)
    S           -> PROFILE_SAVE
    L           -> PROFILE_LOAD
    F12         -> Toggle key-mapping help overlay

Implementation is deferred to Phase 6 (HAL agent).  Once implemented this
module will provide a class that implements the same abstract interface defined
in ``roastmaster.hal.base`` so it can be used interchangeably with the GPIO
backend without changes to the rest of the application.
"""
