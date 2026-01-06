#!/usr/bin/env python3
"""
Regenerate static synopsis pages from database.
Run this script whenever database content changes (states, pueblos, UNESCO sites, etc.).

Usage:
    python regenerate_synopsis.py
"""

import sqlite3
from jinja2 import Environment, FileSystemLoader
import os
from datetime import datetime


def url_for(endpoint, **values):
    """
    Mock Flask's url_for function for static generation.
    Maps Flask routes to static paths.
    """
    # Handle static files
    if endpoint == 'static':
        filename = values.get('filename', '')
        return f"/static/{filename}"

    # Handle other routes (synopsis pages)
    route_map = {
        'synopsis': '/synopsis',
        'synopsis_reference': '/synopsis_reference',
        'synopsis_reference1': '/synopsis_reference1',
        'synopsis_reference2': '/synopsis_reference2',
        'synopsis_reference3': '/synopsis_reference3',
        'questions_multi': '/questions_multi',
        'geography_states': '/geography_states',
    }

    return route_map.get(endpoint, f'/{endpoint}')


def get_db_connection():
    """Connect to database."""
    conn = sqlite3.connect('quiz.db')
    conn.row_factory = sqlite3.Row
    return conn


def generate_geography_reference():
    """Generate static geography reference page from database."""
    print("Generating geography reference page...")

    conn = get_db_connection()

    # Get all states with capitals
    states = conn.execute('SELECT state_name, capital FROM geography_questions ORDER BY state_name').fetchall()

    # Calculate counts (counting multi-state sites only once)
    state_count = conn.execute('SELECT COUNT(*) FROM geography_questions').fetchone()[0]
    pueblo_count = conn.execute('SELECT COUNT(DISTINCT pueblo_name) FROM pueblos_magicos').fetchone()[0]
    unesco_count = conn.execute('SELECT COUNT(DISTINCT site_name) FROM unesco_sites').fetchone()[0]
    arch_count = conn.execute('SELECT COUNT(DISTINCT site_name) FROM archaeological_sites').fetchone()[0]

    # Find multi-state UNESCO sites (with years)
    unesco_multi_state = conn.execute('''
        SELECT us.site_name, ud.year_added, GROUP_CONCAT(us.state_name, ', ') as states, COUNT(*) as state_count
        FROM unesco_sites us
        LEFT JOIN unesco_dates ud ON us.site_name = ud.site_name
        GROUP BY us.site_name
        HAVING state_count > 1
        ORDER BY us.site_name
    ''').fetchall()

    # Find multi-state archaeological sites
    arch_multi_state = conn.execute('''
        SELECT site_name, GROUP_CONCAT(state_name, ', ') as states, COUNT(*) as state_count
        FROM archaeological_sites
        GROUP BY site_name
        HAVING state_count > 1
        ORDER BY site_name
    ''').fetchall()

    # Create superscript mappings and legend data
    unesco_superscripts = {}
    unesco_legend = []
    for idx, site in enumerate(unesco_multi_state, 1):
        # Format site name with year for display
        site_display = site['site_name']
        if site['year_added']:
            site_display = f"{site['site_name']} ({site['year_added']})"

        unesco_superscripts[site['site_name']] = idx
        unesco_legend.append({
            'number': idx,
            'site_name': site_display,
            'states': site['states']
        })

    arch_superscripts = {}
    arch_legend = []
    for idx, site in enumerate(arch_multi_state, 1):
        arch_superscripts[site['site_name']] = idx
        arch_legend.append({
            'number': idx,
            'site_name': site['site_name'],
            'states': site['states']
        })

    # Build a comprehensive geography data structure
    geography_data = []

    for state in states:
        state_name = state['state_name']

        # Get pueblos for this state
        pueblos = conn.execute(
            'SELECT pueblo_name FROM pueblos_magicos WHERE state_name = ? ORDER BY pueblo_name',
            (state_name,)
        ).fetchall()

        # Get UNESCO sites for this state (with years from unesco_dates)
        unesco_sites = conn.execute('''
            SELECT us.site_name, ud.year_added
            FROM unesco_sites us
            LEFT JOIN unesco_dates ud ON us.site_name = ud.site_name
            WHERE us.state_name = ?
            ORDER BY us.site_name
        ''', (state_name,)).fetchall()

        # Get archaeological sites for this state
        archaeological_sites = conn.execute(
            'SELECT site_name FROM archaeological_sites WHERE state_name = ? ORDER BY site_name',
            (state_name,)
        ).fetchall()

        # Format UNESCO sites with years
        unesco_formatted = []
        for site in unesco_sites:
            if site['year_added']:
                unesco_formatted.append(f"{site['site_name']} ({site['year_added']})")
            else:
                unesco_formatted.append(site['site_name'])

        geography_data.append({
            'state': state_name,
            'capital': state['capital'],
            'pueblos': [p['pueblo_name'] for p in pueblos],
            'unesco': unesco_formatted,
            'archaeological': [a['site_name'] for a in archaeological_sites]
        })

    conn.close()

    # Load Jinja2 environment
    env = Environment(loader=FileSystemLoader('templates'))

    # Add Flask's url_for function to the Jinja2 environment
    env.globals['url_for'] = url_for

    template = env.get_template('synopsis_reference2.html')

    # Render template with data
    html_output = template.render(
        geography_data=geography_data,
        unesco_superscripts=unesco_superscripts,
        arch_superscripts=arch_superscripts,
        unesco_legend=unesco_legend,
        arch_legend=arch_legend,
        state_count=state_count,
        pueblo_count=pueblo_count,
        unesco_count=unesco_count,
        arch_count=arch_count,
        generated_date=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )

    # Add generation comment at the top
    generation_comment = f"<!-- STATIC FILE: Auto-generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} by regenerate_synopsis.py -->\n<!-- DO NOT EDIT THIS FILE DIRECTLY - Edit synopsis_reference2.html template and regenerate -->\n"
    html_output = generation_comment + html_output

    # Write to static file
    output_path = os.path.join('templates', 'synopsis_reference2_static.html')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_output)

    print(f"  [OK] Generated {output_path}")
    print(f"       - {state_count} states")
    print(f"       - {pueblo_count} Pueblos Magicos")
    print(f"       - {unesco_count} UNESCO sites")
    print(f"       - {arch_count} Archaeological sites")


def main():
    """Main entry point for regeneration script."""
    print("=" * 60)
    print("Synopsis Static Page Regeneration")
    print("=" * 60)
    print()

    # Check if database exists
    if not os.path.exists('quiz.db'):
        print("Error: quiz.db not found!")
        print("   Make sure you're running this script from the project root directory.")
        return 1

    # Check if templates directory exists
    if not os.path.exists('templates'):
        print("Error: templates directory not found!")
        return 1

    # Check if template exists
    if not os.path.exists(os.path.join('templates', 'synopsis_reference2.html')):
        print("Error: synopsis_reference2.html template not found!")
        return 1

    try:
        # Generate geography reference page
        generate_geography_reference()

        print()
        print("=" * 60)
        print("All synopsis pages regenerated successfully!")
        print("=" * 60)
        print()
        print("Next steps:")
        print("  1. Review the generated file(s) to ensure they look correct")
        print("  2. Update app.py to use the static file (if not already done)")
        print("  3. Test the page in your browser")
        print()
        return 0

    except Exception as e:
        print()
        print("=" * 60)
        print(f"Error during regeneration: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    import sys
    sys.exit(main())
