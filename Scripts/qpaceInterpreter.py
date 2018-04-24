#! /usr/bin/env python3
# qpaceQUIP.py by Jonathan Kessluk
# 4-19-2018, Rev. 1
# Q-Pace project, Center for Microgravity Research
# University of Central Florida
#
# Credit to the SurfSat team for CCDR driver and usage.
#
# The interpreter will be invoked when pin 7 goes high. This will grab QUIP packets and direct them to the packet directory, then decode them.

import time
import SC16IS750
import RPi.GPIO as gpio
from qpaceWTCHandler import initWTCConnection
from qpaceQUIP import Packet
import qpacPiCommands as cmd

PACKET_SIZE = Packet.max_size

INTERP_PACKETS_PATH = "packets/" #TODO determine actual path
INTERP_CMD_SIZE = 2 # How many characters will we expect to be the command length

# Add commands to the map. Format is "String to recognize for command" : function name
COMMAND_LIST = {
    "SD":cmd.immediateShutdown      # Shutdown the Pi
    "RE":cmd.immediateReboot        # Reboot the Pi
    "SF":cmd.sendFile               # Initiate sending files to WTC from the pi filesystem
    "AP":cmd.asynchronusSendPackets # Send specific packets from the Pi to the WTC
    "HI":cmd.pingPi                 # Ping the pi!
    "ST":cmd.returnStatus           # Accumulate status about the operation of the pi, assemble a txt file, and send it. (Invokes sendFile)
    "CS":cmd.checkSiblingPi         # Check to see if the sibling Pi is alive. Similar to ping but instead it's through ethernet
    "PC":cmd.pipeCommandToSiblingPi # Take the args that are in the form of a command and pass it along to the sibling pi through ethernet
    "UC":cmd.performUARTCheck       # Tell the pi to perform a "reverse" ping to the WTC. Waits for a response from the WTC.
}

def _isCommand(query = None):
    """
    Checks to see if the query is a command as defined by the COMMAND_LIST

    Parameters
    ----------
    query - bytes - a query that could be or could not be a command.

    Returns
    -------
    True - If it is a command
    False - If it is not a command
    """
    if query:
        return query[:INTERP_CMD_SIZE].decode('utf-8').upper() in COMMAND_LIST
    else:
        return False

def _processCommand(chip = None, query = None):
    """
    Split the command from the arguments and then run the command as expected.

    Parameters
    ----------
    chip - SC16IS750() - an SC16IS750 object to read/write from/to
    query- bytes - the command string.

    Raises
    ------
    ConnectionError - If a connection to the WTC was not passed to the command
    """
    if not chip:
        raise ConnectionError("Connection to the WTC not established.")
    if query:
        query = query.decode('utf-8')
    cmd = query[:INTERP_CMD_SIZE] # Seperate the specific command
    args = query[INTERP_CMD_SIZE:] # Seperate the args
    COMMAND_LIST[cmd](args) # Run the command

def _processQUIP(chip = None,buf = None):
    #TODO do we need to determine the opcode or can we force the packets to be sent in order?
    #TODO we will need to determine the opcode iff we use control packets.
    """
    Take the data in the buffer and write files to it. We will assume they are QUIP packets.

    Paramters
    ---------
    chip - SC16IS750() - an SC16IS750 object to read/write from/to
    buf - bytes - the input buffer from the WTC

    Raises
    ------
    BufferError - If the buffer is empty, assume that there was a problem.
    ConnectionError - If the connection to the WTC was not passed to this method.
    """
    if not chip:
        raise ConnectionError("Connection to the WTC not established.")
    if not buf:
        raise BufferError("Buffer is empty, no QUIP data received.")

    def isolateOpCode():
        pass

    if len(buf) > 0:
        missedPackets = []
        # write the initial init packet
        try:
            with open(INTERP_PACKETS_PATH+"init.qp",'wb') as f:
                f.write(buf[:PACKET_SIZE])
        except:
            missedPackets.append('init')

        buf = buf[PACKET_SIZE:]
        counter = 0
        attempt = 0
        while len(buf) > 0:
            try:
                with open(INTERP_PACKETS_PATH+str(counter) + ".qp",'wb') as f: # we can just name them with the counter iff we don't determine the opcodes
                    f.write(buf[:PACKET_SIZE])
            except:
                attempt += 1
                if attempt > 1:
                    missedPackets.append(counter)
                    counter+=1
                    buf = buf[PACKET_SIZE:]
            else:
                buf = buf[PACKET_SIZE:]
                counter += 1
        return missedPackets
def run(chip = None):
    """
    This function is the "main" purpose of this module. Placed into a function so that it can be called in another module.

    Parameters
    ----------
    Nothing

    Returns
    -------
    Nothing

    Raises
    ------
    ConnectionError - if the WTC cannot be connected to for some reason.
    BufferError - if the FIFO in the WTC cannot be read OR the buffer was empty.
    All other exceptions raised by this function are passed up the stack or ignored and not raised at all.
    """
    if chip is None:
        chip = initWTCConnection()
        if chip is None:
            raise ConnectionError("A connection could not be made to the WTC.")
    # Initialize the pins
    gpio.set_mode(gpio.BCM)
    gpio.setup(PIN_IRQ_WTC, gpio.IN)

    print("Waiting for data. Hit Ctrl+C to abort.")
    buf = b''
    while True:
        try:
            time.sleep(1)
            attempt = 0
            status = chip.byte_read(SC16IS750.REG_LSR) #checks the status bit to see if there is something in the RHR
            if status & 0x01 == 1: # If LSB of LSR is high, then data available in RHR:
                # See how much we want to read.
                waiting = chip.byte_read(SC16IS750.REG_RXLVL)
                if waiting > 0:
                    for i in range(waiting):
                        # Read from the chip and write to the buffer.
                        buf += chip.byte_read(SC16IS750.REG_RHR)
            # If MSB of LSR is high, then FIFO data error detected:
    		elif status & 0x80 == 1:
                attempt += 1
                if attempt > 1:
                    BufferError("The FIFO could not be read on the WTC.")
            else:
                # If the Interrupt Request pin is Logical Low then break. We don't want to read anymore.
                if not gpio.input(PIN_IRQ_WTC):
                    raise InterruptedError("The WTC has ended transmission")

        except KeyboardInterrupt: # If we get a SIGINT, we can also break off.
            break
        except InterruptedError: # IF we are interrupted, break.
            break
        except BufferError: raise
    try:
        if isCommand(buf): # Is the input to the buffer a command?
            processCommand(chip,buf)
        else:
            processQUIP(chip,buf) # IF it's not a command, assume it's QUIP data.
    except (BufferError,ConnectionError): raise
    gpio.cleanup() #TODO do we actually care to cleanup?
