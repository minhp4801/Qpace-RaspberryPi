#! /usr/bin/env python3
# qpaceLogger.py by Jonathan Kessluk
# 2-20-2018, Rev. 1.2
# Q-Pace project, Center for Microgravity Research
# University of Central Florida

import argparse
import sys
import os
import struct
import time
from math import ceil,log
from itertools import zip_longest

class Packet():
    sync = 0xFFFF           # 2 bytes
    start = 0xABCD          # 2 bytes
    end = 0xDCBA            # 2 bytes
    id_bits = 32            # 4 bytes
    overflow = 0            # 0 for false. (1 bit)
    placeholder_bits = 4    # in bits

    max_size = 256          # in bytes
    data_size = 77          # in bytes
    max_id = 0xFFFFFFFF     # in hex
    packet_data_size = None # packet_data_size in bytes
    last_id = -1            # -1 if there are no packets.

    def __init__(self,data, pid,**kwargs):
        """
        Constructor for a packet.

        Parameters
        ---------
        data - int, str, bytes, bytearray - If a str it must be hex and valid bytes.
        pid - int - Integer to be the PID of the packet. Can not be negative and must be
                    +1 the last pid used.

        Exceptions
        ----------
        ValueError - if the data passed to the packet is too large to fit in the packet.
                     or the pid is out of order.
                     or the pid is negative.
        """
        if pid < 0:
            raise ValueError("Packet pid is invalid. Must be a positive number.")
        # Is the data in a valid data type? If so, convert it to a bytearray.
        if isinstance(data,int):
            data = bytearray(data.to_bytes(data.bit_length()//8+1,byteorder='big'))
        elif isinstance(data,bytearray):
            pass
        elif isinstance(data,bytes):
            data = bytearray(data)
        elif isinstance(data,str):
            try:
                data = bytearray.fromhex(data)
            except ValueError:
                data = bytearray(map(ord,data))

        else:
            TypeError("Input data is of incorrect type. Must input str, int, bytes, or bytearray")

        if 'op_code' in kwargs:
            self.op_code = kwargs['op_code']
        else:
            self.op_code = 0x0

        data_in_bytes = len(data)
        if data_in_bytes <= Packet.data_size: # Make sure the data is below the max bytes
            # Only worry about the PID for packets of code 0x0 and 0x7. anything else does not need a PID
            if self.op_code == 0x0 or self.op_code == 0x7 and (Packet.last_id + 1) == pid:
                Packet.last_id = pid
                self.pid = pid % Packet.max_id # If the pid is > max_id, force it to be smaller!
            elif self.op_code > 0x0 and self.op_code < 0x7:
                self.pid = 0
            else:
                raise ValueError("Packet pid out of order.")
            if pid > Packet.max_id:
                # Set the overflow to 0 for even multiples of pid and 1 for odd.
                Packet.overflow = (Packet.max_id / pid) % 2
            self.data = data
            self.bytes = data_in_bytes

        else:
            raise ValueError("Packet size is too large for the current header information. Data input restricted to " + str(Packet.data_size) + " Bytes.")

    def buildHeader(self):
        """
            Build the header for the packet.

            Returns
            -------
            bytearray - packet header data.
        """
        sync = bytearray(Packet.sync.to_bytes(2,byteorder='big'))  # 2 bytes
        start = bytearray(Packet.start.to_bytes(2,byteorder='big'))# 2 bytes
        pid = bytearray(self.pid.to_bytes(4,byteorder='big'))    # 4 bytes
        header_end = bytearray(((Packet.overflow << 7) | (self.op_code << 4)).to_bytes(1,byteorder='big'))
        return sync + start + (pid + header_end)*3

    def buildData(self):
        """
            Build the data for the packet. All data is repeated 3 times for FEC.

            Returns
            -------
            bytearray - packet data that is triple redundant and interlaced by size of the data
        """
        # Do a TMR expansion where the data is replicated 3 times but not next to each other
        # to avoid burst errors.
        return self.data*3

    def buildFooter(self):
        """
            Build the footer for the packet.

            Returns
            -------
            bytearray - packet footer data.
        """
        sync = bytearray(Packet.sync.to_bytes(2,byteorder='big'))  # 2 bytes
        end = bytearray(Packet.end.to_bytes(2,byteorder='big'))# 2 bytes
        return end + sync

    def build(self):
        """
            Build the entire packet.

            Returns
            -------
            int - the whole packet. if converted to binary/hex it will be the packet.
        """
        header = self.buildHeader()
        data = self.buildData()
        footer = self.buildFooter()
        packet = header + data + footer
        while len(packet) < Packet.max_size:
            packet += bytearray.fromhex('ff')
        return packet

class Encoder():
    def __init__(self,path_for_encode,path_for_packets, suppress=False,destructive=False):
        """
        Constructor for the Encoder.

        Parameters
        ----------
        path_for_encode - str - The path with a filename on it to encode the file.
        path_for_packets - str - where to store the packets.
        suppress - bool - suppress output to the terminal.
        destructive - bool - delete the file when done with it.

        Raises
        ------
        TypeError - raises if the paths aren't valid paths.
        """
        # We want a path for the packets and a file for the decoding.
        if path_for_packets[-1] != '/' or path_for_encode[-1] == '/':
            if path_for_packets == ".":
                path_for_packets = ''
            else:
                raise TypeError("Please provide a valid path for the packets to be found and a valid file to save the data.")
        self.file = path_for_encode
        self.packets = path_for_packets
        self.suppress = suppress
        self.destructive = destructive
        self.packets_built = 0

    def run(self):
        """
        Main method to run for the encoder. This will encode a file into packets.

        Returns
        -------
        True if successful
        False if unsuccessful
        """
        try:
            if self.encode():
                self.buildInitPacket()
            return True

        except Warning:
            print("All packets could not be created.")
            if self.destructive: os.remove(self.packets+"*.qp")
            return False


    def encode(self):
        try:
            with open(self.file,'rb') as fileToEncode:
                if not self.suppress: print("Beginning to encode file into packets.")
                pid = -1 #-1 to start at zero
                try:
                    packetToBuild = None
                    while True: #Until we are done...
                        pid += 1 #choose the next PID in order
                        data = fileToEncode.read(Packet.data_size)
                        if data:
                            packetToBuild = Packet(data,pid)
                        else:
                            # If there's no more data set the last packet created as op_code 0x7
                            self.setLastPacket(packetToBuild)
                            break #If there's nothing else to read, back out. We are done.
                        with open(self.packets+str(pid)+".qp", 'wb') as packet:
                            packet.write(packetToBuild.build())
                except OSError:
                    print("Could not write to the directory: ", self.packets)
                    print("Could not write packet: ", pid)
                    raise OSError
                else:
                    if not self.suppress: print("Successfully built ", pid, " packets.")
                    #self.setAsLastPacket(pid-1) # Set the last packet we wrote as the last packet to transmit.
                    self.packets_built = pid
                    if self.destructive: os.remove(fileToEncode.name)
        except FileNotFoundError:
            print("Can not find file: ", self.file)
        except OSError:
            print("There was a problem encoding: ",self.file)
        else:
            if not self.suppress: print("Finished encoded file into packets.")
            return True
        return False

    def buildInitPacket(self):
        if not self.suppress: print("Creating initialization packet.")
        try:
            info = []
            with open(self.packets+"init.qp",'wb') as packet:
                info.append(self.file.split("/")[-1])
                info.append(str(self.packets_built))
                info.append(str(os.path.getsize(self.file)))
                #info.append(checksum)
                packet.write(Packet(" ".join(info),0,op_code=0x1).build())
        except OSError:
            print("Could not write to initialization packet: init.qp")
            raise Warning

    def setLastPacket(self,packet):
        packet.op_code = 0x7
        with open(self.packets+str(packet.pid)+".qp",'wb') as packetToReWrite:
            packetToReWrite.write(packet.build())

class Decoder():
    def __init__(self, path_for_decode, path_for_packets, suppress=False,destructive=False):
        """
        Constructor for the Encoder.

        Parameters
        ----------
        path_for_encode - str - The path with a filename on it to decode to.
        path_for_packets - str - where the packets are stored.
        suppress - bool - suppress output to terminal
        destructive - bool - delete the packets when done with them.

        Raises
        ------
        TypeError - raises if the paths aren't valid paths.
        """
        # We want a path for the packets and a file for the decoding.
        if path_for_packets[-1] !='/':
            if path_for_packets == ".":
                path_for_packets = ''
            else:
                raise TypeError("Please provide a valid paths for decoding.")
        if path_for_decode[-1] == '/':
            self.file_path = path_for_decode
            self.file_name = None
        else:
            # Split the path and the name apart.
            self.file_path = path_for_decode[:path_for_decode.rfind('/')+1]
            self.file_name = path_for_decode[path_for_decode.rfind('/')+1:]
        self.packets = path_for_packets
        self.suppress = suppress
        self.destructive = destructive

    def run(self):
        """
        Main method to run for the decoder. Takes packets and decodes them into a file.
        """
        # Controller will deal with the packets and naming them
        self.init()
        self.prepareFileLocation()
        missedPackets = self.bulkDecode()
        if missedPackets is None:
            print("complete")
        else:
            print("Attempting an async")
            time.sleep(10)
            self.asyncDecode(1)

    def init(self):
        initPacket = self.readInit()
        if self.file_name is None:
            self.file_name = initPacket[0] # Return what the filename should be.
        self.expected_packets = int(initPacket[1])
        self.file_size = int(initPacket[2])

    def readInit(self):
        information = None
        try:

            with open(self.packets+"init.qp",'rb') as init:
                information = init.read()
                information = Decoder.resolveExpansion(information[19:information.find(bytes.fromhex(hex(Packet.end)[2:]))])
                information = information.decode('utf-8').split(' ')
        except OSError:
            print("Could not read init file from ", self.packets)
            raise OSError
        return information

    def bulkDecode(self):
        """
        Returns
        -------
        None if successful
        A list of pids of packets missed.
        """
        missedPackets = []
        newFile = None
        try:
            if not self.suppress: print("Beginning to decode packets into a file.")
            newFile = self.file_path+self.file_name
            if os.path.exists(newFile):
                if not self.suppress: print("File already exists. Overwriting with new data (", newFile,")")
                os.remove(newFile)
            with open(newFile+".scaff", 'rb+') as scaffoldToBuild:
                pid = -1 # -1 to start at zero
                scaffold_data = ""
                while True: # Until we are done...
                    try:
                        pid += 1
                        # Try to open the file. If it can't find it, then it will throw a
                        # FileNotFoundError to indicate that we are complete.
                        with open(self.packets+str(pid)+".qp",'rb') as packet:
                            packet_data = packet.read()

                            # Remove the sync and start bits, thus [4:19]
                            # header = self.decipherHeader(Decoder.resolveExpansion(packet_data[4:19]))
                            # We only care about the data here, so 19 onward
                            information = Decoder.resolveExpansion(packet_data[19:packet_data.find(bytes.fromhex(hex(Packet.end)[2:]))])
                            scaffold_data = self.ammendScaffoldData(scaffold_data,information.decode('utf-8'),pid)

                    except FileNotFoundError as e:
                        # If the next packet exists
                        #TODO what if two packets were lost!!! REDO to handle a big jump in packets
                        if os.path.exists(self.packets+str(pid+1)+".qp"):
                            missedPackets.append(pid)
                            # Ammend the scaffold with placeholder bytes
                            # ÿ if 0xFF
                            scaffold_data = self.ammendScaffoldData(scaffold_data,'ÿ'*Packet.data_size,pid)
                        else:
                            try:
                                # Write the scaffold data to the file
                                scaffoldToBuild.write(bytearray(scaffold_data,'utf-8'))
                            except OSError:
                                print("Failed to write scaffold data.")
                            else:
                                if not self.suppress: print("Completed read of packets.")
                                break #This is important to get out of the While Loop
                    except OSError:
                        print("Could not open packet for reading: packet ", pid)
        except OSError:
            print("Could not open file for writing: ", newFile or self.file_path)
        else:
            if missedPackets:
                if not self.suppress: print("Packets missing during decoding. Scaffold intact.")
                return missedPackets
            else:
                if not self.suppress: print("Successfully decoded packets into a file.")
                self.buildScaffold()
                return None


    def prepareFileLocation(self):
        # Open a file and write to it placeholder characters for the actual data.
        with open(self.file_path+self.file_name+".scaff",'wb') as tempFile:
            tempFile.write(b' '*self.file_size)

    def ammendScaffoldData(self,scaffold_data,to_write,pid):
        """
        scaffold_data-list of strings
        to_write-str
        pid - int
        returns a string
        """

        # Every Packet.data_size bytes, split into a list.
        scaffold_data = list(map(''.join, zip_longest(*[iter(scaffold_data)]*Packet.data_size, fillvalue='')))
        try:
            scaffold_data[pid]=to_write
        except IndexError:
            scaffold_data.append(to_write)
        return ''.join(scaffold_data)

    def buildScaffold(self):
        newFile = self.file_path+self.file_name
        os.rename(newFile+".scaff",newFile)

    def asyncDecode(self,pid):
        """
        pid - int - pid of the packet to be integrated into the file asynchronously
        """
        try:
            if self.file_name is None: raise Warning("File name is not set. This can happen if an Asynchronous Decode is done before the Bulk Decode.")
            information = None
            with open(self.packets+str(pid)+".qp",'br') as packet:
                # Read the packet, give us only the information field. Resolve the TMR expansion.
                try:
                    packet_data = packet.read()
                except OSError as err:
                    print("Unable to read the packet: ",self.packets+str(pid)+".qp")
                    raise err
                information = Decoder.resolveExpansion(packet_data[19:packet_data.find(bytes.fromhex(hex(Packet.end)[2:]))])
            try:
                scaffold_data = None
                with open(self.file_path+self.file_name+".scaff",'rb') as scaffold:
                    scaffold_data = self.ammendScaffoldData(scaffold.read().decode('utf-8'),information.decode('utf-8'),pid)
                with open(self.file_path+self.file_name+".scaff",'w') as scaffold:
                    # Write the scaffold data to the file
                    scaffold.write(scaffold_data)
            except OSError as err:
                print("Unable to write to the scaffold: ", self.file_path+self.file_name+".scaff")
                raise err
        except FileNotFoundError:
            print("Packet(",pid,") not found. Maybe it is not in the correct directory? (",self.packets,")")
        except OSError:
            pass
        except Warning as err:
            print(err,"\nAttempting to read init packet and resolve the problem...")
            try:
                self.init()
            except OSError as err:
                newErr = OSError("Unable to read the init packet.")
                print(err,"\n",newErr)
                raise newErr

        else:
            return True #If successful
        return False #If unsuccessful


    @staticmethod
    def resolveExpansion(information,size=None):
        majority_info = bytearray()
        if size is None:
            size = len(information)//3
        for i in range(0,size):
            vote = (information[i],information[i + size],information[i + size * 2])
            majority_info += bytes([(max(set(vote), key = vote.count))])
        return majority_info

    @staticmethod
    def decipherHeader(header):
        header_dict = {}
        # Header: sync(2) - start(2)- pid(4)- [overflow(1),op(3),reserved(4)](1)
        header_dict['pid'] = struct.unpack('>L',header[0:4])[0] # Convert byte array to int.
        header_dict['overflow'] = (header[4] >> 7) & 1  # Bit mask to get the first bit
        header_dict['op_code'] =  (header[4] >> 4) & 7  # Bit mask to get the 2nd - 4th bits
        return header_dict




class Controller():
    def __init__(self, coder):

        if isinstance(coder,Encoder) or isinstance(coder,Decoder):
            self.coder = coder
        else: raise TypeError("Invalid type: "+str(type(coder))+". Must initialize an encoder or decoder.")

    def begin(self):
        if isinstance(coder,Encoder):
            coder.run()
        else: # If it's not an encoder, we know it's a decoder.
            coder.run()

    def communicate(self):
        pass
# Code to be run after importing everything.
# -------------------------------------------

if __name__ == '__main__':
    print("TODO: Asynchronous file building based on pid.")
    print("TODO: Add function comments!!!!!")
    print("TODO: Determine exceptions and where they will be raised")
    print("TODO: Line 343")
    print("TODO: what if the packet missing is the last packet?")
    parser = argparse.ArgumentParser(description='Interat with QUIP and encode/decode packets.')
    parser.add_argument('--version',action='version', version = 'Version: 1.2')
    mutex_group = parser.add_mutually_exclusive_group(required=True)

    parser.add_argument('-s','--suppress',
                        help="hide the terminal outputs.",
                        default=False,
                        action='store_true')
    parser.add_argument('--destructive',
                        help="delete the file or packets when the script is done with them",
                        default=False,
                        action='store_true')
    mutex_group.add_argument('-e','--encode',
                        help="set to encode.",
                        default=False,
                        action='store_true')
    mutex_group.add_argument('-d','--decode',
                        help="set to decode.",
                        default=False,
                        action='store_true')
    parser.add_argument('-p','--packets',
                        dest="packet_location",
                        help="set the path of packets.",
                        type=str)
    parser.add_argument('-f','--file',
                        dest='file_location',
                        help="set the path of the file.",
                        type=str)

    args = parser.parse_args()  # Parse the args coming in from the user
    ctrl = None
    try:
        if args.encode:
            coder = Encoder(args.file_location,args.packet_location,suppress=args.suppress,destructive=args.destructive)
        else:
            coder = Decoder(args.file_location,args.packet_location,suppress=args.suppress,destructive=args.destructive)

        ctrl = Controller(coder)
    except TypeError as err:
        print("Error: ",err)
        exit()

    ctrl.begin()



