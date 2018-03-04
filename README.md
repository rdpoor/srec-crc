# srec-crc
Install a CRC into a .srec format file, honored by the KBoot 2.0 Bootloader Protocol

## Prerequisites

You will need a copy of [python](https://www.python.org/downloads/) and [SRecord 1.64](http://srecord.sourceforge.net/).

## Typical usage:
To install a CRC into the Bootloader Configuration (BCA) of a .srec format file:

    python update_crc.py -d -b 0x43c0 -o "../Install/myproject-crc.srec" "myproject.srec"
    
* -d : print additional debugging information
* -b 0x43c0 : specify the location of the BCA within the .srec file (default is 0x83c0)
* -o "../Install/myproject-crc.srec" : specify the destination file (default is stdout)
* "myproject.srec" : the source file

## Integration with KDS 

I found it helpful to create the following `post-build.sh` file and specify it as 
a post-build step in KDS.  It inserts the CRC in the project file and copies it 
(along with the .elf and .map files) to an Install directory:

    #!/bin/bash
    #
    # Install CRC into a .srec file, as required by the flash-resident bootloader.
    #
    # This script is by the KDS IDE after a successful build.  To see where this
    # is called in KDS, see:
    #
    # Project => Properties => C/C++ Build => Settings => Build Steps => post-build steps
    # 
    
    PROJECT=myproject
    
    mkdir -p ../Install
    # save files useful for debugging
    cp -p ${PROJECT}.elf {$PROJECT}.map ../Install/
    # compute CRC and install in ${PROJECT}-crc.srec binary image
    python ../tools/update_crc.py -d -b 0x43c0 -o "../Install/${PROJECT}-crc.srec" "${PROJECT}.srec"
