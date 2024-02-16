import pcbnew


"""
LED matrix layout creator.
NOTE: this currently assumes an even matrix, e.g. 16x16 as opposed to 15x15.
Will likely break in the latter case.
"""


LEDS = range(7, 263)
CAPS = range(12, 268)

SPACE_X         = 120        # mils
SPACE_Y         = 120        # mils
LED_TO_CAP      = 60         # mils
TRACK_OFFSET    = 30         # mils

ROW_LEN         = 16

# PCBNew stores things in nanometer
MILS_TO_NM = 0.0254 * 1e6


# this might as well be global
PCB = pcbnew.CreateEmptyBoard()
LAYERS = {PCB.GetLayerName(i): i for i in PCB.GetEnabledLayers().CuStack()}


class LEDPairing:
    def __init__(self, led_ref, cap_ref, idx):
        self.led_ref = led_ref
        self.cap_ref = cap_ref

        self.led = PCB.FindModuleByReference("D%s" % str(self.led_ref))
        self.cap = PCB.FindModuleByReference("C%s" % str(self.cap_ref))

        self.row = idx / ROW_LEN
        self.col = idx % ROW_LEN


def run():
    assert len(LEDS) == len(CAPS)
    assert ROW_LEN % 2 == 0

    led_pairings = [LEDPairing(d, c, idx) for idx, (d, c) in enumerate(zip(LEDS, CAPS))]

    position_components(led_pairings)
    run_tracks(led_pairings)

    pcbnew.Refresh()


def position_components(led_pairings):
    for idx, pairing in enumerate(led_pairings):
        led = pairing.led
        cap = pairing.cap

        led_orientation = (idx + 1) % 2 * 90
        if led.GetOrientationDegrees() != led_orientation:
            led.SetOrientationDegrees(led_orientation)

        cap_orientation = (idx + 1) % 2 * 180
        if cap.GetOrientationDegrees() != cap_orientation:
            cap.SetOrientationDegrees(cap_orientation)

        led_position = pcbnew.wxPoint(
            pairing.col * SPACE_X * MILS_TO_NM,
            pairing.row * SPACE_Y * MILS_TO_NM,
        )
        led.SetPosition(led_position)
        led.Reference().SetVisible(False)

        # adjust cap position so that the 5V tracks are perfectly straight
        led_pad = list(led.Pads())[1]
        cap_pad = list(cap.Pads())[1]

        led_pad_offset = led_pad.GetPosition().x - led.GetPosition().x
        cap_pad_offset = cap_pad.GetPosition().x - cap.GetPosition().x
        cap_center_offset = led_pad_offset - cap_pad_offset

        cap_position = pcbnew.wxPoint(
            led_position[0] + cap_center_offset,
            led_position[1] + LED_TO_CAP * MILS_TO_NM,
        )
        cap.SetPosition(cap_position)
        cap.Reference().SetVisible(False)


def run_tracks(led_pairings):
    # reset current tracks
    tracks = PCB.GetTracks()
    for t in tracks:
        # if type(t) is pcbnew.TRACK and t.IsSelected():
        #     PCB.Delete(t)
        PCB.Delete(t)


    # run signal traces between leds and 5V decoupling trace for led/cap pairs
    for i, pairing in enumerate(led_pairings[:-1]):
        next_pairing = led_pairings[i+1]
        if pairing.col != ROW_LEN - 1:
            _between_leds(pairing.led, next_pairing.led)
        else:
            _between_rows(pairing.led, next_pairing.led)

        _between_led_cap(pairing.led, pairing.cap)

    # run 5V traces for pairs of leds and add vias in betwween
    # then run a 5V bus on the back copper
    for i, pairing in enumerate(led_pairings[::2]):
        idx = i * 2
        next_pairing = led_pairings[idx+1]
        _between_caps(pairing.cap, next_pairing.cap, pairing.col)


def _run_track_between_points(from_point, to_point, netcode, layer, width):
    t = pcbnew.TRACK(PCB)
    PCB.Add(t)

    t.SetStart(from_point)
    t.SetEnd(to_point)
    t.SetNetCode(netcode)
    t.SetLayer(layer)
    t.SetWidth(width)


def _run_track_between_pads(from_pad, to_pad):
    _run_track_between_points(
        from_pad.GetPosition(),
        to_pad.GetPosition(),
        from_pad.GetNetCode(),
        from_pad.GetLayer(),
        from_pad.GetNet().GetTrackWidth(),
    )


def _between_caps(from_cap, to_cap, from_column):
    from_cap_pad = list(from_cap.Pads())[1]
    to_cap_pad = list(to_cap.Pads())[1]
    _run_track_between_pads(from_cap_pad, to_cap_pad)

    via_pos = pcbnew.wxPoint(
        (from_cap_pad.GetPosition().x + to_cap_pad.GetPosition().x) / 2,
        (from_cap_pad.GetPosition().y + to_cap_pad.GetPosition().y) / 2,
    )

    via = pcbnew.VIA(PCB)
    PCB.Add(via)
    via.SetPosition(via_pos)
    via.SetNetCode(from_cap_pad.GetNetCode())
    via.SetDrill(from_cap_pad.GetNet().GetViaDrillSize())
    via.SetWidth(from_cap_pad.GetNet().GetViaSize())

    # for first column via's, run track outward
    # NOTE: can do any length needed here
    if from_column == 0:
        _run_track_between_points(
            via_pos,
            via_pos + pcbnew.wxPointMils(SPACE_X * (ROW_LEN - 1), 0),
            from_cap_pad.GetNetCode(),
            LAYERS["B.Cu"],
            from_cap_pad.GetNet().GetTrackWidth(),
        )


def _between_leds(from_led, to_led):
    from_led_pad = list(from_led.Pads())[2]
    to_led_pad = list(to_led.Pads())[0]
    _run_track_between_pads(from_led_pad, to_led_pad)


def _between_led_cap(led, cap):
    led_pad = list(led.Pads())[1]
    cap_pad = list(cap.Pads())[1]
    _run_track_between_pads(led_pad, cap_pad)


def _between_rows(from_led, to_led):
    from_pad = list(from_led.Pads())[2]
    from_pad_pos = from_pad.GetPosition()

    to_pad = list(to_led.Pads())[0]
    to_pad_pos = to_pad.GetPosition()

    # Front copper: run out from last column to via
    _run_track_between_points(
        from_pad_pos,
        from_pad_pos + pcbnew.wxPointMils(TRACK_OFFSET, 0),
        from_pad.GetNetCode(),
        from_pad.GetLayer(),
        from_pad.GetNet().GetTrackWidth(),
    )

    # Add via
    via = pcbnew.VIA(PCB)
    PCB.Add(via)
    via.SetPosition(from_pad_pos + pcbnew.wxPointMils(TRACK_OFFSET, 0))
    via.SetNetCode(from_pad.GetNetCode())
    via.SetDrill(from_pad.GetNet().GetViaDrillSize())
    via.SetWidth(from_pad.GetNet().GetViaSize())

    # Back copper: run from via to first column
    _run_track_between_points(
        from_pad_pos + pcbnew.wxPointMils(TRACK_OFFSET, 0),
        pcbnew.wxPoint(to_pad_pos.x, from_pad_pos.y),
        from_pad.GetNetCode(),
        LAYERS["B.Cu"],
        from_pad.GetNet().GetTrackWidth(),
    )
    # Back copper: kink downwards at 45 degrees
    _run_track_between_points(
        pcbnew.wxPoint(to_pad_pos.x, from_pad_pos.y),
        pcbnew.wxPoint(
            to_pad_pos.x - TRACK_OFFSET * MILS_TO_NM,
            from_pad_pos.y + TRACK_OFFSET * MILS_TO_NM,
        ),
        from_pad.GetNetCode(),
        LAYERS["B.Cu"],
        from_pad.GetNet().GetTrackWidth(),
    )
    # Back copper: run down to via
    _run_track_between_points(
        pcbnew.wxPoint(
            to_pad_pos.x - TRACK_OFFSET * MILS_TO_NM,
            from_pad_pos.y + TRACK_OFFSET * MILS_TO_NM,
        ),
        pcbnew.wxPoint(to_pad_pos.x - TRACK_OFFSET * MILS_TO_NM, to_pad_pos.y),
        from_pad.GetNetCode(),
        LAYERS["B.Cu"],
        from_pad.GetNet().GetTrackWidth(),
    )

    # Add via
    via = pcbnew.VIA(PCB)
    PCB.Add(via)
    via.SetPosition(
        pcbnew.wxPoint(to_pad_pos.x - TRACK_OFFSET * MILS_TO_NM, to_pad_pos.y)
    )
    via.SetNetCode(from_pad.GetNetCode())
    via.SetDrill(from_pad.GetNet().GetViaDrillSize())
    via.SetWidth(from_pad.GetNet().GetViaSize())

    # Front copper: run from via to first column pad
    _run_track_between_points(
        pcbnew.wxPoint(to_pad_pos.x - TRACK_OFFSET * MILS_TO_NM, to_pad_pos.y),
        to_pad_pos,
        from_pad.GetNetCode(),
        to_pad.GetLayer(),
        to_pad.GetNet().GetTrackWidth(),
    )


run()
