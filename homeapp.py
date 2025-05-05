#!/usr/bin/python

import asyncio
import json, yaml
import websockets
import pprint, sys

from urllib import request, error
from yaml import safe_load as load

pp = pprint.PrettyPrinter(indent=2)
pp = pp.pprint


configs = {
        'default': (
            'My Home',
            'homeapp-myhome',
            'myhome.yaml',
            'localhost',
            'TOKEN via "Long-lived access tokens" from Home Assistant'
        ),
        'myhome2': (
            'Dashboard Name',
            'dashboard-path',
            'filename.yaml',
            'Home Assistant IP address or name',
            'TOKEN via "Long-lived access tokens" from Home Assistant'
        ),
}

# check for local settings
try:
    from configs import configs
except:
    pass

if len(sys.argv) > 1:
    config = sys.argv[1]
else:
    config = 'default'
home_name, dashboard_name, config_name, ha_host, bearer_token = configs[config]
home_name = 'My Home'


# The tabs at the top of the page
views = [
    [ 'home', home_name, 'mdi:home' ],
    [ 'climate', 'Climate', 'mdi:fan' ],
    [ 'light', 'Lights', 'mdi:lightbulb' ],
    [ 'security', 'Security', 'mdi:security' ],
    [ 'media', 'Media', 'mdi:music' ],
    [ 'water', 'Water', 'mdi:water' ],
]

view_chips = {
    'home': { 'chips': ['motion', 'light', 'fan', 'cover', 'security', 'alarm_control_panel',
                        'media_player', 'climate', 'irrigation'] },
    'all_areas': { 'chips': ['temperature', 'humidity', 'light', 'cover', 'fan', 'security',
                             'media_player', 'climate', 'alarm_control_panel', 'irrigation'] },
    'climate': { 'chips': ['fan', 'cover', 'climate'] },
    'light': { 'chips': 'light' },
    'media': { 'chips': 'media_player' },
    'security': { 'chips': ['motion', 'security', 'alarm_control_panel'] },
    'water': { 'chips': ['fan', 'humidity', 'irrigation'],
               'areas': 'garden' },
}

climate_domains = ( 'climate', 'fan' )
light_domains = ( 'light', )
media_domains = ( 'media_player', )
security_domains = ( 'alarm_control_panel', 'lock', 'security' )
water_domains = ( 'irrigation', )

# all possible device classes for domain "cover"
all_cover_deviceclasses = ( 'awning', 'blind', 'curtain', 'damper', 'door', 'garage', 'gate', 'shade', 'shutter', 'window' )

# split into security and non-security related
sec_cover_deviceclasses = ( 'door', 'garage', 'gate', 'window' )
non_sec_cover_deviceclasses = ( 'awning', 'blind', 'curtain', 'damper', 'shade', 'shutter' )

# binary_sensor security related device classes
bin_sensor_deviceclasses = ( 'door', 'garage_door', 'lock', 'tamper', 'window' )

# all security related device classes (union(sec_cover_deviceclasses, bin_sensor_deviceclasses))
security_deviceclasses = ( 'door', 'garage', 'garage_door', 'gate', 'lock', 'tamper', 'window' )

'''
These are "active" when they're closed while HA sees all covers as active when
open.  For awnings, doors, windows, etc. that makes sense but not for e.g. shades
so reverse the visual cues.
'''
rev_open_close = ( "shade", )

ALARM_ARM_HOME = 1
ALARM_ARM_AWAY = 2
ALARM_ARM_NIGHT = 4
ALARM_TRIGGER = 8
ALARM_ARM_CUSTOM_BYPASS = 16
ALARM_ARM_VACATION = 32

COVER_SET_POSITION = 0x4

FAN_SET_SPEED = 0x1
FAN_OSCILLATE = 0x2
FAN_DIRECTION = 0x4

api_url = "http://%s:8123/api" % ha_host

def build_api_request(query):
    req = request.Request(api_url + '/' + query)
    req.add_header('Authorization', 'Bearer ' + bearer_token)
    req.add_header('Content-Type', 'application/json')
    return req

def ha_query(q):
    req = build_api_request(q)
    with request.urlopen(req) as f:
        return json.loads(f.read().decode('utf-8'))

def ha_template_query(t):
    req = build_api_request('template')
    data = json.dumps({ "template": "{{ %s }}" % t })
    data = data.encode('ascii')
    with request.urlopen(req, data) as f:
        r = f.read().decode('utf-8')
        if isinstance(r, str) and r[0] == '[' and r[-1] == ']':
            # if r is a string representing a list make it an actual list
            r = eval(r)
        return r

favorite_entities = ha_template_query("label_entities('favorite')")
home_view_entities = ha_template_query("label_entities('on_home_view')")
summary_entities = ha_template_query("label_entities('in_summaries')")
hidden_entities = ha_template_query("states|map(attribute='entity_id')|select('is_hidden_entity')|list")

all_entities = dict((e['entity_id'], e) for e in ha_query('states') if e['entity_id'] not in hidden_entities)

light_groups = [e for e,v in all_entities.items() if v['entity_id'].startswith('light.') and v['attributes'].get('entity_id')]

# Rainmachine sprinklers, these need special handling
rm_sprinklers = [e for e,v in all_entities.items()
                 if e.startswith('switch.')
                 and v['attributes'].get('sprinkler_head_type')]

async def get_areas():
    uri = "ws://%s:8123/api/websocket" % ha_host
    areas = {}
    ix = 1
    async with websockets.connect(uri) as websocket:
        await websocket.recv()
        await websocket.send(json.dumps({ "type": "auth", "access_token": bearer_token }))
        await websocket.recv()
        # There's no area_id for these from states via API, so get via WS.
        # NOTE: the area also has to be explicitly set by turning off "Use device
        # area" and selecting an area, otherwise the area_id is still just None
        for rs in rm_sprinklers:
            await websocket.send(json.dumps({ "id": ix, "type": "config/entity_registry/get", "entity_id": rs }))
            e = await websocket.recv()
            e = json.loads(e)['result']
            all_entities[rs]['area_id'] = e['area_id']
            ix += 1
        # Get area details which are not available via the API
        await websocket.send(json.dumps({ "id": ix, "type": "config/area_registry/list" }))
        area_list = await websocket.recv()
        area_list = json.loads(area_list)['result']
        for area in area_list:
            areas[area['area_id']] = area
    return areas

all_areas = asyncio.get_event_loop().run_until_complete(get_areas())

area_ids = sorted(all_areas.keys())
area_entities = dict((a, ha_template_query("area_entities('%s') | reject('is_hidden_entity') | list" % a)) for a in area_ids)

home_favorites_header = '''
    type: grid
    cards:
    - type: heading
      heading: Favorites
      heading_style: title
'''

def is_card_active(entity):
    domain = entity.split('.')[0]

    if domain == 'cover' and get_attr(entity, 'device_class') in rev_open_close:
        # flip open/closed visual
        tmpl = '''
            style:
              mushroom-shape-icon$: |
                .shape {
                   background-color: {{ "rgba(var(--default-blue), 0.2)" if states(config.entity)=="closed" else "var(--shape-color-disabled)" }} !important;
                }
              .: |
                ha-card {
                  background-color: {{ "white" if states(config.entity)=="closed" else "rgba(0, 0, 0, 0.1)" }};
                }
                ha-state-icon {
                  color: {{ "rgb(var(--rgb-state-cover-open))" if states(config.entity)=="closed" else "rgb(var(--rgb-state-cover-closed))" }};
                }
        '''
        return load(tmpl)

    is_active = {
        'alarm_control_panel': ('!=', 'disarmed'),
        'cover': ('!=', 'closed'),
        'lock': ('!=', 'locked'),
        'media_player': ('==', 'playing'),
    }
    active = '%s"%s"' % is_active.get(domain, ('==', 'on'))
    tmpl = '''
        style: |
          ha-card {
            {% if state_attr(config.entity, 'hvac_action') != none %}
              background-color: {{ "rgba(0, 0, 0, 0.1)" if is_state_attr(config.entity, 'hvac_action', 'idle') else "white" }};
            {% else %}
              background-color: {{ "white" if states(config.entity)''' + active + ''' else "rgba(0, 0, 0, 0.1)" }};
            {% endif %}
          }
    '''
    if domain == 'lock':
        # This removes the button
        # NOTE: ha-card indentation must be same as in tmpl above!!!
        tmpl += '''
          ha-card div.actions {
            display: none;
          }
    '''
    return load(tmpl)

def range_chip(kind, area):
    icons = {
        'humidity': 'mdi:water-percent',
        'temperature': 'mdi:thermometer',
    }
    if area:
        if isinstance(area, (list, tuple)):
            s = '(%s)' % '+'.join("area_entities('%s')" % a for a in area)
        else:
            s = "area_entities('%s')" % area
        entities = s + " | reject('is_hidden_entity')"
        navtgt = "%s_%s" % (area, kind)
    else:
        entities = "label_entities('in_summaries')"
        navtgt = kind

    tmpl = '''
        type: template
        content: |-
          {% from "summaries.jinja" import min_max_range %}''' + '''
          {{ min_max_range("%s", %s) }}''' % (kind, entities) + '''
        tap_action:
          action: navigate
          navigation_path: ''' + "/%s/%s" % (dashboard_name, navtgt) + '''
        card_mod:
          style: |
            ha-card {
              {% from "summaries.jinja" import deviceclass_count %}
              {% ''' + 'set n = deviceclass_count("%s", %s)' % (kind, entities) + ''' %}
              {{ "display: none !important;" if n|int == 0 }}
            }
        icon: ''' + icons[kind]
    return load(tmpl)

def count_chip(kind, area):
    # (icon, color, navpath)
    parms = {
        'alarm_control_panel': ( 'mdi:shield-lock', '#4caf50', 'security' ),
        'climate': ( 'mdi:thermostat', '#2196f3', 'climate' ),
        'cover': ( 'mdi:blinds-horizontal', 'blue', 'climate' ),
        'fan': ( 'mdi:fan', '#4caf50', 'climate' ),
        'irrigation': ( 'mdi:sprinkler', 'blue', 'water' ),
        'light': ( 'mdi:lightbulb-multiple', '#ff9800', 'light' ),
        'motion': ( 'mdi:motion-sensor', 'grey', 'security' ),
        'media_player': ( 'mdi:music', 'grey', 'media' ),
        'security': ( 'mdi:security', '#67e3e0', 'security' ),
    }
    domain = kind
    if area:
        if isinstance(area, (list, tuple)):
            s = '(%s)' % '+'.join("area_entities('%s')" % a for a in area)
        else:
            s = "area_entities('%s')" % area
        entities = '%s | reject("is_hidden_entity") | reject("in", %s)' % (s, light_groups)
    else:
        entities = 'label_entities("in_summaries")'

    if kind == 'climate':
        entities += "|expand|selectattr('attributes.hvac_action', 'defined')"
        entities += "|selectattr('attributes.hvac_action', 'ne', 'idle')"
        entities += "|selectattr('entity_id', 'has_value')|map(attribute='entity_id')|list"

    if kind == 'irrigation':
        domain = 'switch'
        entities += "|select('in', %s)|list" % rm_sprinklers

    if kind == 'motion':
        domain = 'binary_sensor'
        entities += "|expand|selectattr('attributes.device_class', 'defined')"
        entities += "|selectattr('attributes.device_class', 'eq', 'motion')"
        entities += "|selectattr('entity_id', 'has_value')|map(attribute='entity_id')|list"

    if kind == 'alarm_control_panel':
        count = "domain_state_count('%s', 'ne', 'disarmed', %s)" % (domain, entities)
    elif kind == 'climate':
        # the entity list only contains entities that have attribute hvac_action
        # and are not idle (selected above) so just count all of them
        count = "domain_state_count('%s', 'ne', 'dummy_never_matches', %s)" % (domain, entities)
    elif kind == 'cover':
        count = "cover_count(%s, %s, %s)" % (entities, rev_open_close, security_deviceclasses)
    elif kind == 'media_player':
        count = "domain_state_count('%s', 'eq', 'playing', %s)" % (domain, entities)
    elif kind == 'security':
        count = "security_count(%s, %s)" % (entities, security_deviceclasses)
    else:
        count = "domain_state_count('%s', 'eq', 'on', %s)" % (domain, entities)
    tmpl = '''
        type: template
        content: |-
          {% from "summaries.jinja" import cover_count, domain_state_count, security_count %}
          {% set n = ''' + count + ''' %}
          {{ n }}
        card_mod:
          style: |
            ha-card {
              {% from "summaries.jinja" import cover_count, domain_state_count, security_count %}
              {% set n = ''' + count + ''' %}
              {{ "display: none !important;" if n|int == 0 }}
            }
    '''
    y = load(tmpl)
    icon, color, navtgt = parms.get(kind, (None, None, None))
    if icon: y['icon'] = icon
    if color: y['icon_color'] = color
    if navtgt: y['tap_action'] = { 'action': 'navigate', 'navigation_path': '/%s/%s' % (dashboard_name, navtgt) }
    return y

def get_attr(entity, field):
    return all_entities[entity]['attributes'].get(field)

def gen_header():
    tmpl = '''
        kiosk_mode:
          hide_overflow: true
          hide_dialog_light_color_actions: true
          non_admin_settings:
            hide_sidebar: true
            hide_menubutton: true
    '''
    return load(tmpl)

def gen_views():
    return [ gen_view(*v) for v in views ]

def gen_areas():
    return [ gen_area(i) for i in area_ids ]

def gen_lists():
    r = [ gen_temperature_list() ] + [ gen_humidity_list() ]
    r += [ t for t in [ gen_temperature_list(i) for i in area_ids ] if t ]
    r += [ h for h in [ gen_humidity_list(i) for i in area_ids ] if h ]
    return r

def gen_list(area, kind, name):
    if area:
        l = gen_list_sections(area, kind)
        icon = all_areas[area]['icon']
        n = "%s_%s" % (area, kind)
    else:
        l = gen_summary_list_sections(kind)
        icon = 'mdi:fan'
        n = kind
    if l:
        s = gen_subview_settings(n, name, icon)
        s['sections'] = l
        return s
    return []

def gen_humidity_list(area=None):
    return gen_list(area, 'humidity', 'Humidity')

def gen_temperature_list(area=None):
    return gen_list(area, 'temperature', 'Temperature')

def gen_list_sections(area, kind):
    aes = [ e for e in area_entities[area]
            if get_attr(e, 'device_class') == kind]
    if aes:
        sf = gen_area_header(area)
        sf['cards'] += [ gen_card(e, area) for e in
                         sorted(aes, key=lambda e: get_attr(e, 'friendly_name')) ]
        return [ sf ]
    return []

def gen_summary_list_sections(kind):
    sf = []
    for area in area_ids:
        aes = [ e for e in area_entities[area]
                if e in summary_entities
                and get_attr(e, 'device_class') == kind]
        if aes:
            sa = gen_area_header(area)
            sa['cards'] += [ gen_card(e, area) for e in aes ]
            sf += [ sa ]
    return sf

def gen_view(view, name, icon):
    s = gen_view_settings(view, name, icon)
    s['header'] = gen_view_header(name)
    s['background'] = gen_view_background()
    s['sections'] = view == 'home' and gen_home_sections() \
                                    or gen_view_sections(view)
    return s

def gen_area(area):
    a = all_areas[area]
    name = a['name']
    icon = a['icon']
    s = gen_subview_settings(area, name, icon)
    s['background'] = gen_view_background()
    s['sections'] = gen_area_sections(area)
    return s

def gen_view_settings(view, name, icon):
    tmpl = f'''
        type: sections
        max_columns: 4
        title: {name}
        icon: {icon}
        path: {view}
    '''
    return load(tmpl)

def gen_subview_settings(view, name, icon):
    y = gen_view_settings(view, name, icon)
    y['subview'] = True
    return y

def gen_view_header(name):
    tmpl = '''
        card:
          type: heading
          heading: "%s"
          heading_style: title
          badges:
            - type: entity
              show_state: true
              show_icon: true
              entity: sensor.summary_temperature
              icon: mdi:thermometer
              tap_action:
                action: navigate
                navigation_path: /%s/temperature
            - type: entity
              show_state: true
              show_icon: true
              entity: sensor.summary_humidity
              icon: mdi:water-percent
              tap_action:
                action: navigate
                navigation_path: /%s/humidity
          card_mod:
            style: |
              ha-card div.content.title {
                font-size: 28px;
                font-weight: 692;
                line-height: 32px;
              }
    ''' % (name, dashboard_name, dashboard_name)
    return load(tmpl)

def gen_view_background():
    tmpl = '''
        opacity: 100
        alignment: center
        size: cover
        repeat: repeat
        attachment: fixed
        image: /local/view_background.jpg
    '''
    return load(tmpl)

def gen_chips(view, area=None):
    chip_funcs = {
        'alarm_control_panel': count_chip,
        'climate': count_chip,
        'cover': count_chip,
        'fan': count_chip,
        'humidity': range_chip,
        'irrigation': count_chip,
        'light': count_chip,
        'media_player': count_chip,
        'motion': count_chip,
        'security': count_chip,
        'temperature': range_chip,
    }
    tmpl = '''
        type: custom:mushroom-chips-card
    '''
    chip_spec = view_chips.get(view)
    if chip_spec:
        chips = chip_spec['chips']
        if not isinstance(chips, (list, tuple)):
            chips = [chips]
        if not area:
            area = chip_spec.get('areas')
        chip_list = [ chip_funcs[chip](chip, area) for chip in chips ]
        if chip_list:
            card = load(tmpl)
            card['chips'] = chip_list
            return [card]
    return []

def classify_domain(entity):
    domain = entity.split('.')[0]
    if domain == 'cover':
        if get_attr(entity, 'device_class') in security_deviceclasses:
            return 'security'
        else:
            return 'climate'
    if domain == 'fan':
        return 'climate'
    if domain == 'switch' and entity in rm_sprinklers:
        return 'irrigation'
    return domain

def order_entities(domain, entities):
    if domain != 'light':
        return sorted(entities)
    g = sorted(e for e in entities if e in light_groups)
    ng = sorted(e for e in entities if e not in light_groups)
    return g + ng

def gen_view_sections(view):
    sf = gen_chips(view)
    try:
        domains = eval(view + '_domains')
    except:
        return sf

    for area in area_ids:
        aes = [ e for e in area_entities[area]
               if classify_domain(e) in domains]
        if aes:
            sa = gen_area_header(area)
            sa['cards'] += [ gen_card(e, area) for e in order_entities(view, aes) ]
            sf += [ sa ]
    return sf

def gen_area_sections(area):
    sf = gen_chips('all_areas', area)

    for (domain, name, icon) in views:
        if domain == 'home':
            continue
        try:
            domains = eval(domain + '_domains')
        except:
            continue
        aes = [ e for e in area_entities[area]
               if classify_domain(e) in domains]
        if aes:
            sa = gen_area_header(area, name, domain)
            sa['cards'] += [ gen_card(e, area) for e in order_entities(domain, aes) ]
            sf += [ sa ]
    return sf

def gen_card(entity, area):
    f = 'gen_%s_card' % entity.split('.')[0]
    try:
        f = eval(f)
        c = f(entity, area)
        if get_attr(entity, 'entity_picture'):
            c['icon_type'] = 'entity-picture'
        return c
    except:
        return gen_basic_card(entity, area)

def gen_basic_card(entity, area):
    tmpl = f'''
        type: custom:mushroom-entity-card
        entity: {entity}
    '''
    return load(tmpl)

def gen_alarm_control_panel_card(entity, area):
    on_home_view = area == 'home'
    states = []
    sf = get_attr(entity, 'supported_features')
    if sf & ALARM_ARM_HOME: states.append('armed_home')
    if sf & ALARM_ARM_AWAY: states.append('armed_away')
    if sf & ALARM_ARM_NIGHT: states.append('armed_night')
    # Don't show these on card, activate via popup
    # if sf & ALARM_ARM_CUSTOM_BYPASS: states.append('armed_custom_bypass')
    # if sf & ALARM_ARM_VACATION: states.append('armed_vacation')

    tmpl = f'''
        type: custom:mushroom-alarm-control-panel-card
        entity: {entity}
    '''
    y = load(tmpl)
    if not on_home_view:
        y['states'] = states
        y['layout'] = 'horizontal'
    y['card_mod'] = is_card_active(entity)
    return y

def gen_climate_card(entity, area):
    on_home_view = area == 'home'

    tmpl = f'''
        type: custom:mushroom-climate-card
        entity: {entity}
        tap_action:
          action: more-info
    '''
    y = load(tmpl)
    y['show_temperature_control'] = not on_home_view
    if not on_home_view:
        modes = get_attr(entity, 'hvac_modes')
        if modes:
            y['hvac_modes'] = modes
        y['layout'] = 'horizontal'
    y['card_mod'] = is_card_active(entity)
    return y

def gen_cover_card(entity, area):
    on_home_view = area == 'home'
    sf = get_attr(entity, 'supported_features')
    can_position = (sf & COVER_SET_POSITION) != 0

    tmpl = f'''
        type: custom:mushroom-cover-card
        entity: {entity}
    '''
    y = load(tmpl)
    y['show_buttons_control'] = not on_home_view
    if not on_home_view:
        y['show_position_control'] = can_position
        y['layout'] = 'horizontal'
    else:
        y['fill_container'] = False
    y['card_mod'] = is_card_active(entity)
    return y

def gen_fan_card(entity, area):
    on_home_view = area == 'home'
    sf = get_attr(entity, 'supported_features')
    can_set_speed = (sf & FAN_SET_SPEED) != 0
    can_oscillate = (sf & FAN_OSCILLATE) != 0
    can_set_direction = (sf & FAN_DIRECTION) != 0

    tmpl = f'''
        type: custom:mushroom-fan-card
        entity: {entity}
        icon_animation: true
    '''
    y = load(tmpl)
    if on_home_view:
        y['fill_container'] = False
    else:
        y['show_percentage_control'] = can_set_speed
        y['show_oscillate_control'] = can_oscillate
        y['show_direction_control'] = can_set_direction
        y['layout'] = 'horizontal'
    y['card_mod'] = is_card_active(entity)
    return y

def gen_light_card(entity, area):
    on_home_view = area == 'home'

    brightness = color_temp = color = onoff = False
    # NOTE: does not handle color w/o brightness case
    if not on_home_view:
        scm = get_attr(entity, 'supported_color_modes')
        if scm:
            scm = scm[0]
        if scm == 'onoff':
            onoff = True
        elif scm == 'brightness':
            brightness = True
        elif scm == 'color_temp':
            brightness = True
            color_temp = True
        elif scm in [ 'hs', 'xy', 'rgb', 'rgbw', 'rgbww' ]:
            brightness = True
            color = True
    tmpl = f'''
        type: custom:mushroom-light-card
        entity: {entity}
    '''
    y = load(tmpl)
    if not on_home_view:
        y['show_color_control'] = color
        y['layout'] = onoff and 'default' or 'horizontal'
    y['use_light_color'] = not on_home_view
    y['show_brightness_control'] = brightness
    y['show_color_temp_control'] = color_temp
    y['fill_container'] = onoff
    y['card_mod'] = is_card_active(entity)
    return y

def gen_lock_card(entity, area):
    tmpl = f'''
        type: custom:mushroom-lock-card
        entity: {entity}
        layout: horizontal
        grid_options:
          columns: 6
          rows: 1
        tap_action:
          action: toggle
    '''
    y = load(tmpl)
    y['card_mod'] = is_card_active(entity)
    return y

def gen_media_player_card(entity, area):
    on_home_view = area == 'home'
    sf = get_attr(entity, 'supported_features')

    tmpl = f'''
        type: custom:mushroom-media-player-card
        entity: {entity}
        use_media_info: true
        show_volume_level: false
        icon_type: entity-picture
        tap_action:
          action: more-info
        hold_action:
          action: none
        double_tap_action:
          action: none
    '''
    y = load(tmpl)
    if sf and not on_home_view:
        y['media_controls'] = [ 'previous', 'play_pause_stop', 'next' ]
        y['layout'] = 'horizontal'
    y['card_mod'] = is_card_active(entity)
    return y

def gen_switch_card(entity, area):
    tmpl = f'''
        type: custom:mushroom-entity-card
        entity: {entity}
        tap_action:
          action: toggle
    '''
    y = load(tmpl)
    if entity in rm_sprinklers:
        y['icon'] = 'mdi:sprinkler-variant'
    y['card_mod'] = is_card_active(entity)
    return y

def gen_temperature_card(entity, area):
    tmpl = f'''
        type: custom:mushroom-entity-card
        entity: {entity}
    '''
    return load(tmpl)

def gen_area_header(area, name=None, navtgt=None):
    if not name:
        name = all_areas[area]['name']
    if not navtgt:
        navtgt = area
    tmpl = f'''
        type: grid
        cards:
        - type: heading
          heading: {name}
          heading_style: title
          tap_action:
            action: navigate
            navigation_path: /{dashboard_name}/{navtgt}
    '''
    return load(tmpl)

def gen_home_sections():
    sf = gen_chips('home')

    fv = load(home_favorites_header)
    fv['cards'] += [ gen_card(f, 'home') for f in favorite_entities ]
    sf += [ fv ]

    for area in area_ids:
        aes = area_entities[area]
        hes = set(aes) & set(home_view_entities)
        if hes:
            sa = gen_area_header(area)
            sa['cards'] += [ gen_card(e, 'home') for e in sorted(hes) ]
            sf += [ sa ]
    return sf

def gen_all():
    s = gen_header()
    s['views'] = gen_views()
    s['views'] += gen_areas()
    s['views'] += gen_lists()
    return s

s = gen_all()
#pp(s)

with open(config_name, 'w') as f:
    f.write(yaml.dump(s))
