# update_crc.py: write crc into Bootloader Configuration Area of .srec file
#
# Author: Robert Poor <rdpoor@gmail.com>, October 2017
#
# SYNOPSIS:
#
#    python update_crc.py [args] <source_file>.srec 
#
# EXAMPLE:
#
#    python update_crc.py -b 0x43c0 -o my_image_w_checksum.srec my_image.srec
#
# Desription: update_crc computes the CRC of a .srec file so that it will be
# honored by the KBoot 2.0 Bootloader protocol.  It reads the crcStartAddress
# and crcByteCount fields of the files's Bootloader Configuration Area (BCA) in 
# order establish the range of the CRC calculation, computes the CRC, and then
# updates the crcExpectedValue slot of the BCA before emitting the modified
# .srec file
#
# Implementation note: This program makes heavy use of the srec_cat command line
# program, and consequently expects to find the srec_cat in the user's search
# path.  For more information on srec_cat, please consult:
#    http://srecord.sourceforge.net/man/man1/srec_cat.html
#
# TODO: check to see if the BCA has sensible values in it (not just BCA_TAG)
#
# TODO: allow the user to update arbitrary fields in the BCA from the commmand
#       line, not just the CRC field

import argparse
import re
import subprocess
import sys
import tempfile

__version__ = '2017-10-28'
DEFAULT_BCA_ADDRESS = 0x83c0
DEFAULT_OUTPUT_FILE = '-'

SREC_CAT = "/usr/local/bin/srec_cat"

# Magic cookie indicating a valid Bootloader Configuration Area
BCA_KEY = 0x6766636b    # 'kfcg' as a uint32

# Value indicating that CRC checking is disabled
BCA_UNDEFINED = 0xffffffff

# Offset of the computed CRC within the BCA header
COMPUTED_CRC_OFFSET = 0xc

debug = False

def debug_print(s):
    global debug
    if (debug):
        stderr_print(s)

def stderr_print(s):
    sys.stderr.write(str(s)+'\n')

# ==============================================================================
# extracting info from Bootloader Configuration Area (BCA)

def get_bca_info(filename, bca_address):
    """
    Read the BCA section of the filename and extract parameters, returning
    them in a dictionary with keys: 
        'bca_key'
        'crc_start_address'
        'crc_end_address'
    """
    s = read_bca(filename, bca_address)
    d = parse_bca(s)
    return d

def read_bca(filename, bca_address):
    """
    Return the BCA as a string.  Assumes that the format will be of the form:
    000043C0: 6B 63 66 67 00 40 00 00 00 BC 00 00 0B 28 8A 9C  #kcfg.@...<...(..
    """
    # Generates a string for the srec_cat utility program and then invokes it,
    # capturing and returing its standard output.
    script = generate_bca_script(filename, bca_address)
    with tempfile.NamedTemporaryFile() as temp:
        temp.write(script)
        temp.flush()
        # for v2.x:
        s = subprocess.check_output([SREC_CAT, "@" + temp.name])
        # for v3.x:
        # result = subprocess.run(["srec_cat", "@" + temp.name], stdout=subprocess.PIPE)
        # str = result.stdout
    return s
    
def generate_bca_script(source_file, bca_address):
    bca_end_address = bca_address + 0x10    
    template = """{source_file} -crop {bca_address} {bca_end_address} -output -hex-dump"""
    return template.format(source_file=source_file,
                           bca_address=bca_address,
                           bca_end_address=bca_end_address)

# Expect a string of the form:
# 000043C0: 6B 63 66 67 00 40 00 00 00 BC 00 00 0B 28 8A 9C  #kcfg.@...<...(..
#          | k  c  f  g|  crcStart |  crcCount |crcExpected|
def parse_bca(s):
    m = re.search(r":((?: [0-9A-F][0-9A-F]){16})\s+#", s, re.IGNORECASE)
    if m == None:
        # didn't match
        return None

    hex_digits = m.group(1)
    # e.g. " 6B 63 66 67 00 40 00 00 00 BC 00 00 0B 28 8A 9C"
    bca_key = parse_hex_le(hex_digits, 0)
    crc_start_address = parse_hex_le(hex_digits, 12)
    crc_count = parse_hex_le(hex_digits, 24)
    crc_expected = parse_hex_le(hex_digits, 36)
    d = {
        'bca_key':bca_key,
        'crc_start_address':crc_start_address,
        'crc_end_address':crc_start_address + crc_count,
        'crc_expected':crc_expected
        }
    return d

# specialized parser for hex strings of the form:
# ' 6B 63 66 67' => 0x6766636B
def parse_hex_le(s, offset):
    tot = 0
    for i in range(0,4):
        sub_str = s[offset:offset+3]
        val = int(sub_str, 16)
        tot += val << i*8
        offset += 3
    return tot

# ==============================================================================
#

def generate_srec_cat_script(params):
    """Create a script to pass to srec_cat that computes and inserts the CRC"""
    if (params['crc_start_address'] >= params['computed_crc_address_end']
        or params['crc_end_address'] <= params['computed_crc_address']):
        return generate_script_nonoverlapping(params)
    else:
        return generate_script_overlapping(params)
    

def generate_script_nonoverlapping(params):
    """
    Generate a script for srec_cat for situations where the computed CRC 
    does not span the CRC value itself.
    """
    template = """# Insert CRC into BCA of a .srec file
{source_file}
-fill 0xff {crc_start_address:#x} {crc_end_address:#x}
-crop {crc_start_address:#x} {crc_end_address:#x}

# Pass the stream through the CRC algorithm, emitting
# the computed CRC at computed_crc_address
-bit-reverse -crc32-b-e 0x0 -bit-reverse
-xor 0xff
-crop 0x0 0x4
-offset {computed_crc_address:#x}

# Carve a hole in the source file for the computed CRC
{source_file}
# (Optional: uncomment next line to fill holes with 0xff)
# -fill 0xff {crc_start_address:#x} {crc_end_address:#x}
-exclude {computed_crc_address:#x} {computed_crc_address_end:#x}
"""
    return template.format(**params)


def generate_script_overlapping(params):
    """
    Generate a script for srec_cat for situations where the computed CRC 
    spans the CRC value itself.
    """

    
    template = """# Insert CRC into BCA of a .srec file
# Replicate the input with the expectedCRC field elided by shifting
# everything above expectedCRC down by one word.
(
{source_file}
-fill 0xff {crc_start_address:#x} {crc_end_address:#x}
-crop {crc_start_address:#x} {computed_crc_address:#x}

{source_file}
-fill 0xff {crc_start_address:#x} {crc_end_address:#x}
-crop {computed_crc_address_end:#x} {crc_end_address:#x}
-offset -4
)

# Pass the elided stream through the CRC algorithm, emitting
# the computed CRC at computed_crc_address
-bit-reverse -crc32-b-e 0x0 -bit-reverse
-xor 0xff
-crop 0x0 0x4
-offset {computed_crc_address:#x}

# Carve a hole in the source file for the computed CRC
{source_file}
# (Optional: uncomment next line to fill holes with 0xff)
# -fill 0xff {crc_start_address:#x} {crc_end_address:#x}
-exclude {computed_crc_address:#x} {computed_crc_address_end:#x}
"""
    return template.format(**params)



def update_crc(args):

    debug_print('Reading from ' + args.source_file)
    
    bca_info = get_bca_info(args.source_file, args.bca_address)

    if bca_info is None:
        stderr_print('could not find Bootloader Configuration Area')
        return None

    if bca_info['bca_key'] != BCA_KEY:
        stderr_print('Bootloader Configuration Area Key mismatch')
        return None
    
    debug_print('Found BCA at {0:#x}: crc_start_adress = {1:#x}, crc_end_address = {2:#x}'.format(
        args.bca_address,
        bca_info['crc_start_address'],
        bca_info['crc_end_address']
    ))
        
    params = {
        'source_file':args.source_file,
        'crc_start_address':bca_info['crc_start_address'],
        'crc_end_address':bca_info['crc_end_address'],
        'computed_crc_address':args.bca_address + COMPUTED_CRC_OFFSET,
        'computed_crc_address_end':args.bca_address + COMPUTED_CRC_OFFSET + 4
        }

    
    srec_cat_script = generate_srec_cat_script(params)

    with tempfile.NamedTemporaryFile() as temp:
        temp.write(srec_cat_script)
        temp.flush()
        s = subprocess.check_output([SREC_CAT, "@" + temp.name])

    if args.output_file == '-':
        debug_print('Writing to standard output...')
        print s
    else:
        debug_print('Writing to ' + args.output_file + '...')
        with open(args.output_file, 'w') as output_file:
            output_file.write('%s\n' % s)
            
    debug_print('Done!')

    
def main(args):
    global debug
    debug = args.debug
    update_crc(args)

# ==============================================================================
# CLI

def auto_int(x):
    """The auto_int method allows the user to specify integers arguments in the form of '24' or '0x1a'"""
    return int(x, 0)

parser = argparse.ArgumentParser(description='Update CRC in Bootloader Configuration Area')
parser.add_argument('source_file',
                    help='name of .srec source file')
parser.add_argument('-b', '--bca_address', type=auto_int, default=DEFAULT_BCA_ADDRESS,
                    help='address of Bootloader Configuration Area in image (default: 0x%(default)x)')
parser.add_argument('-o', '--output_file', default=DEFAULT_OUTPUT_FILE,
                    help='Specify output file (- for stdout) (default:%(default)s)')
parser.add_argument('-v', '--version', action='version',
                    version='%(prog)s {version}'.format(version=__version__))
parser.add_argument('-d', '--debug', action='store_true',
                    help='print debuggint info to stderr')

# ==============================================================================
#
if __name__ == '__main__':
    args = parser.parse_args()
    main(args)

