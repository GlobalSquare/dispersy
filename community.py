"""
the community module provides the Community base class that should be used when a new Community is
implemented.  It provides a simplified interface between the Dispersy instance and a running
Community instance.

@author: Boudewijn Schoon
@organization: Technical University Delft
@contact: dispersy@frayja.com
"""

from hashlib import sha1
from itertools import islice
from random import random, Random, randint
from time import time

from bloomfilter import BloomFilter
from conversion import BinaryConversion, DefaultConversion
from crypto import ec_generate_key, ec_to_public_bin, ec_to_private_bin
from decorator import documentation, runtime_duration_warning
from dispersy import Dispersy
from distribution import SyncDistribution
from math import ceil
from member import DummyMember, Member
from resolution import PublicResolution, LinearResolution, DynamicResolution
from revision import update_revision_information
from timeline import Timeline

if __debug__:
    from dprint import dprint

# update version information directly from SVN
update_revision_information("$HeadURL$", "$Revision$")

class Community(object):
    @classmethod
    def get_classification(cls):
        """
        Describes the community type.  Should be the same across compatible versions.
        @rtype: unicode
        """
        return cls.__name__.decode("UTF-8")

    @classmethod
    def create_community(cls, my_member, *args, **kargs):
        """
        Create a new community owned by my_member.

        Each unique community, that exists out in the world, is identified by a public/private key
        pair.  When the create_community method is called such a key pair is generated.

        Furthermore, my_member will be granted permission to use all the messages that the community
        provides.

        @param my_member: The Member that will be granted Permit, Authorize, and Revoke for all
         messages.
        @type my_member: Member

        @param args: optional arguments that are passed to the community constructor.
        @type args: tuple

        @param kargs: optional keyword arguments that are passed to the community constructor.
        @type args: dictionary

        @return: The created community instance.
        @rtype: Community
        """
        assert isinstance(my_member, Member), my_member
        assert my_member.public_key, my_member.database_id
        assert my_member.private_key, my_member.database_id
        ec = ec_generate_key(u"high")
        master = Member(ec_to_public_bin(ec), ec_to_private_bin(ec))

        database = Dispersy.get_instance().database
        database.execute(u"INSERT INTO community (master, member, classification) VALUES(?, ?, ?)", (master.database_id, my_member.database_id, cls.get_classification()))
        community_database_id = database.last_insert_rowid

        try:
            # new community instance
            community = cls.load_community(master, *args, **kargs)
            assert community.database_id == community_database_id
            assert community._global_time == 0

            # create the dispersy-identity for the master member
            message = community.create_dispersy_identity(sign_with_master=True)
            assert message.distribution.global_time == 1

            # create my dispersy-identity
            message = community.create_dispersy_identity()
            assert message.distribution.global_time == 2

            # authorize MY_MEMBER
            permission_triplets = []
            for message in community.get_meta_messages():
                # grant all permissions for messages that use LinearResolution or DynamicResolution
                if isinstance(message.resolution, (LinearResolution, DynamicResolution)):
                    for allowed in (u"authorize", u"revoke", u"permit"):
                        permission_triplets.append((my_member, message, allowed))

                    # ensure that undo_callback is available
                    if message.undo_callback:
                        # we do not support undo permissions for authorize, revoke, undo-own, and
                        # undo-other (yet)
                        if not message.name in (u"dispersy-authorize", u"dispersy-revoke", u"dispersy-undo-own", u"dispersy-undo-other"):
                            permission_triplets.append((my_member, message, u"undo"))

                # grant authorize, revoke, and undo permission for messages that use PublicResolution
                # and SyncDistribution.  Why?  The undo permission allows nodes to revoke a specific
                # message that was gossiped around.  The authorize permission is required to grant other
                # nodes the undo permission.  The revoke permission is required to remove the undo
                # permission.  The permit permission is not required as the message uses
                # PublicResolution and is hence permitted regardless.
                elif isinstance(message.distribution, SyncDistribution) and isinstance(message.resolution, PublicResolution):
                    # ensure that undo_callback is available
                    if message.undo_callback:
                        # we do not support undo permissions for authorize, revoke, undo-own, and
                        # undo-other (yet)
                        if not message.name in (u"dispersy-authorize", u"dispersy-revoke", u"dispersy-undo-own", u"dispersy-undo-other"):
                            for allowed in (u"authorize", u"revoke", u"undo"):
                                permission_triplets.append((my_member, message, allowed))

            if permission_triplets:
                community.create_dispersy_authorize(permission_triplets, sign_with_master=True, forward=False)

        except:
            # undo the insert info the database
            # TODO it might still leave unused database entries referring to the community id
            database.execute(u"DELETE FROM community WHERE id = ?", (community_database_id,))

            # raise the exception because this shouldn't happen
            raise

        else:
            return community

    @classmethod
    def join_community(cls, master, my_member, *args, **kargs):
        """
        Join an existing community.

        Once you have discovered an existing community, i.e. you have obtained the public master key
        from a community, you can join this community.

        Joining a community does not mean that you obtain permissions in that community, those will
        need to be granted by another member who is allowed to do so.  However, it will let you
        receive, send, and disseminate messages that do not require any permission to use.

        @param master: The master member that identified the community that we want to join.
        @type master: DummyMember or Member

        @param my_member: The member that will be granted Permit, Authorize, and Revoke for all
         messages.
        @type my_member: Member

        @param args: optional argumets that are passed to the community constructor.
        @type args: tuple

        @param kargs: optional keyword arguments that are passed to the community constructor.
        @type args: dictionary

        @return: The created community instance.
        @rtype: Community
        """
        assert isinstance(master, DummyMember)
        assert isinstance(my_member, Member)
        assert my_member.public_key, my_member.database_id
        assert my_member.private_key, my_member.database_id
        if __debug__: dprint("joining ", cls.get_classification(), " ", master.mid.encode("HEX"))

        database = Dispersy.get_instance().database
        database.execute(u"INSERT INTO community(master, member, classification) VALUES(?, ?, ?)",
                         (master.database_id, my_member.database_id, cls.get_classification()))
        community_database_id = database.last_insert_rowid

        try:
            # new community instance
            community = cls.load_community(master, *args, **kargs)
            assert community.database_id == community_database_id

            # create my dispersy-identity
            community.create_dispersy_identity()

        except:
            # undo the insert info the database
            # TODO it might still leave unused database entries referring to the community id
            database.execute(u"DELETE FROM community WHERE id = ?", (community_database_id,))

            # raise the exception because this shouldn't happen
            raise

        else:
            return community

    @classmethod
    def get_master_members(cls):
        if __debug__: dprint("retrieving all master members owning ", cls.get_classification(), " communities")
        execute = Dispersy.get_instance().database.execute
        return [Member(str(public_key)) if public_key else DummyMember(str(mid))
                for mid, public_key,
                in list(execute(u"SELECT m.mid, m.public_key FROM community AS c JOIN member AS m ON m.id = c.master WHERE c.classification = ?",
                                (cls.get_classification(),)))]

    @classmethod
    def load_community(cls, master, *args, **kargs):
        """
        Load a single community.

        Will raise a ValueError exception when cid is unavailable.

        @param master: The master member that identifies the community.
        @type master: DummyMember or Member

        @return: The community identified by master.
        @rtype: Community
        """
        assert isinstance(master, DummyMember)
        if __debug__: dprint("loading ", cls.get_classification(), " ", master.mid.encode("HEX"))
        community = cls(master, *args, **kargs)

        # tell dispersy that there is a new community
        community._dispersy.attach_community(community)

        return community

    def __init__(self, master):
        """
        Initialize a community.

        Generally a new community is created using create_community.  Or an existing community is
        loaded using load_community.  These two methods prepare and call this __init__ method.

        @param master: The master member that identifies the community.
        @type master: DummyMember or Member
        """
        assert isinstance(master, DummyMember)
        if __debug__:
            dprint("initializing:  ", self.get_classification())
            dprint("master member: ", master.mid.encode("HEX"), "" if isinstance(master, Member) else " (using DummyMember)")

        # dispersy
        self._dispersy = Dispersy.get_instance()

        # _pending_callbacks contains all id's for registered calls that should be removed when the
        # community is unloaded.  most of the time this contains all the generators that are being
        # used by the community
        self._pending_callbacks = []

        try:
            self._database_id, member_public_key, self._database_version = self._dispersy.database.execute(u"SELECT community.id, member.public_key, database_version FROM community JOIN member ON member.id = community.member WHERE master = ?", (master.database_id,)).next()
        except StopIteration:
            raise ValueError(u"Community not found in database [" + master.mid.encode("HEX") + "]")
        if __debug__: dprint("database id:   ", self._database_id)

        self._cid = master.mid
        self._master_member = master
        self._my_member = Member(str(member_public_key))
        if __debug__: dprint("my member:     ", self._my_member.mid.encode("HEX"))
        assert self._my_member.public_key, [self._database_id, self._my_member.database_id, self._my_member.public_key]
        assert self._my_member.private_key, [self._database_id, self._my_member.database_id, self._my_member.private_key]
        if not self._master_member.public_key and self.dispersy_enable_candidate_walker and self.dispersy_auto_download_master_member:
            self._pending_callbacks.append(self._dispersy.callback.register(self._download_master_member_identity))

        # pre-fetch some values from the database, this allows us to only query the database once
        self.meta_message_cache = {}
        for database_id, name, cluster, priority, direction in self._dispersy.database.execute(u"SELECT id, name, cluster, priority, direction FROM meta_message WHERE community = ?", (self._database_id,)):
            self.meta_message_cache[name] = {"id":database_id, "cluster":cluster, "priority":priority, "direction":direction}
        # define all available messages
        self._meta_messages = {}
        self._initialize_meta_messages()
        # cleanup pre-fetched values
        self.meta_message_cache = None

        # define all available conversions
        conversions = self.initiate_conversions()
        assert len(conversions) > 0
        self._conversions = dict((conversion.prefix, conversion) for conversion in conversions)
        # the last conversion in the list will be used as the default conversion
        self._conversions[None] = conversions[-1]

        # the global time.  zero indicates no messages are available, messages must have global
        # times that are higher than zero.
        self._global_time, = self._dispersy.database.execute(u"SELECT MAX(global_time) FROM sync WHERE community = ?", (self._database_id,)).next()
        if self._global_time is None:
            self._global_time = 0
        assert isinstance(self._global_time, (int, long))
        self._acceptable_global_time_cache = self._global_time
        self._acceptable_global_time_deadline = 0.0
        if __debug__: dprint("global time:   ", self._global_time)

        # sync range bloom filters
        if __debug__:
            b = BloomFilter(self.dispersy_sync_bloom_filter_bits, self.dispersy_sync_bloom_filter_error_rate)
            dprint("sync bloom:    size: ", int(ceil(b.size // 8)), ";  capacity: ", b.get_capacity(self.dispersy_sync_bloom_filter_error_rate), ";  error-rate: ", self.dispersy_sync_bloom_filter_error_rate)

        # initial timeline.  the timeline will keep track of member permissions
        self._timeline = Timeline(self)
        self._initialize_timeline()

        # random seed, used for sync range
        self._random = Random(self._cid)
        self._nrsyncpackets = 0

    def _download_master_member_identity(self):
        assert not self._master_member.public_key
        if __debug__: dprint("using dummy master member")

        def on_dispersy_identity(message):
            if message and not self._master_member:
                if __debug__: dprint(self._cid.encode("HEX"), " received master member")
                assert message.authentication.member.mid == self._master_member.mid
                self._master_member = message.authentication.member
                assert self._master_member.public_key

        delay = 2.0
        while not self._master_member.public_key:
            try:
                public_key, = self._dispersy.database.execute(u"SELECT public_key FROM member WHERE id = ?", (self._master_member.database_id,)).next()
            except StopIteration:
                pass
            else:
                if public_key:
                    if __debug__: dprint(self._cid.encode("HEX"), " found master member")
                    self._master_member = Member(str(public_key))
                    assert self._master_member.public_key
                    break

            for candidate in islice(self._dispersy.yield_random_candidates(self), 1):
                if __debug__: dprint(self._cid.encode("HEX"), " asking for master member from ", candidate)
                self._dispersy.create_missing_identity(self, candidate, self._master_member, on_dispersy_identity)
                break

            yield delay
            delay = min(300.0, delay * 1.1)

    def _initialize_meta_messages(self):
        assert isinstance(self._meta_messages, dict)
        assert len(self._meta_messages) == 0

        # obtain dispersy meta messages
        for meta_message in self._dispersy.initiate_meta_messages(self):
            assert meta_message.name not in self._meta_messages
            self._meta_messages[meta_message.name] = meta_message

        # obtain community meta messages
        for meta_message in self.initiate_meta_messages():
            assert meta_message.name not in self._meta_messages
            self._meta_messages[meta_message.name] = meta_message

        if __debug__:
            sync_interval = 5.0
            for meta_message in self._meta_messages.itervalues():
                if isinstance(meta_message.distribution, SyncDistribution) and meta_message.batch.max_window >= sync_interval:
                    dprint("when sync is enabled the interval should be greater than the walking frequency.  otherwise you are likely to receive duplicate packets [", meta_message.name, "]", level="warning")

    def _initialize_timeline(self):
        # load existing permissions from the database
        try:
            authorize = self.get_meta_message(u"dispersy-authorize")
            revoke = self.get_meta_message(u"dispersy-revoke")
            dynamic_settings = self.get_meta_message(u"dispersy-dynamic-settings")

        except KeyError:
            if __debug__: dprint("unable to load permissions from database [could not obtain 'dispersy-authorize' or 'dispersy-revoke' or 'dispersy-dynamic-settings']", level="warning")

        else:
            mapping = {authorize.database_id:authorize.handle_callback, revoke.database_id:revoke.handle_callback, dynamic_settings.database_id:dynamic_settings.handle_callback}

            for packet, in list(self._dispersy.database.execute(u"SELECT packet FROM sync WHERE meta_message IN (?, ?, ?) ORDER BY global_time, packet",
                                                                (authorize.database_id, revoke.database_id, dynamic_settings.database_id))):
                message = self._dispersy.convert_packet_to_message(str(packet), self, verify=False)
                if message:
                    if __debug__: dprint("processing ", message.name)
                    mapping[message.database_id]([message], initializing=True)
                else:
                    # TODO: when a packet conversion fails we must drop something, and preferably check
                    # all messages in the database again...
                    if __debug__: dprint("invalid message in database", level="error")

    # @property
    def __get_dispersy_auto_load(self):
        """
        When True, this community will automatically be loaded when a packet is received.
        """
        # currently we grab it directly from the database, should become a property for efficiency
        return bool(self._dispersy.database.execute(u"SELECT auto_load FROM community WHERE master = ?",
                                                    (self._master_member.database_id,)).next()[0])

    # @dispersu_auto_load.setter
    def __set_dispersy_auto_load(self, auto_load):
        """
        Sets the auto_load flag for this community.
        """
        assert isinstance(auto_load, bool)
        self._dispersy.database.execute(u"UPDATE community SET auto_load = ? WHERE master = ?",
                                        (1 if auto_load else 0, self._master_member.database_id))
    # .setter was introduced in Python 2.6
    dispersy_auto_load = property(__get_dispersy_auto_load, __set_dispersy_auto_load)

    @property
    def dispersy_auto_download_master_member(self):
        """
        Enable or disable automatic downloading of the dispersy-identity for the master member.
        """
        return True

    @property
    def dispersy_enable_candidate_walker(self):
        """
        Enable the candidate walker.

        When True is returned, the dispersy_take_step method will be called periodically.  Otherwise
        it will be ignored.  The candidate walker is enabled by default.
        """
        return True

    @property
    def dispersy_enable_candidate_walker_responses(self):
        """
        Enable the candidate walker responses.

        When True is returned, the community will be able to respond to incoming
        dispersy-introduction-request and dispersy-puncture-request messages.  Otherwise these
        messages are left undefined and will be ignored.

        When dispersy_enable_candidate_walker returns True, this property must also return True.
        The default value is to mirror self.dispersy_enable_candidate_walker.
        """
        return self.dispersy_enable_candidate_walker

    @property
    def dispersy_sync_bloom_filter_error_rate(self):
        """
        The error rate that is allowed within the sync bloom filter.

        Having a higher error rate will allow for more items to be stored in the bloom filter,
        allowing more items to be syced with each sync interval.  Although this has the disadvantage
        that more false positives will occur.

        A false positive will mean that if A sends a dispersy-sync message to B, B will incorrectly
        believe that A already has certain messages.  Each message has -error rate- chance of being
        a false positive, and hence B will not be able to receive -error rate- percent of the
        messages in the system.

        This problem can be aleviated by having multiple bloom filters for each sync range with
        different prefixes.  Because bloom filters with different prefixes are extremely likely (the
        hash functions md5, sha1, shaxxx ensure this) to have false positives for different packets.
        Hence, having two of three different bloom filters will ensure you will get all messages,
        though it will take more rounds.

        @rtype: float
        """
        return 0.01

    # @property
    # def dispersy_sync_bloom_filter_redundancy(self):
    #     """
    #     The number of bloom filters, each with a unique prefix, that are used to represent one sync
    #     range.

    #     The effective error rate for a sync range then becomes redundancy * error_rate.

    #     @rtype: int
    #     """
    #     return 3

    @property
    def dispersy_sync_bloom_filter_bits(self):
        """
        The size in bits of this bloom filter.

        Note that the amount must be a multiple of eight.

        The sync bloom filter is part of the dispersy-introduction-request message and hence must
        fit within a single MTU.  There are several numbers that need to be taken into account.

        - A typical MTU is 1500 bytes

        - A typical IP header is 20 bytes.  However, the maximum IP header is 60 bytes (this
          includes information for VPN, tunnels, etc.)

        - The UDP header is 8 bytes

        - The dispersy header is 2 + 20 + 1 + 20 + 8 = 51 bytes (version, cid, type, member,
          global-time)

        - The signature is usually 60 bytes.  This depends on what public/private key was chosen.
          The current value is: self._my_member.signature_length

        - The other payload is 6 + 6 + 6 + 1 + 2 = 21 (destination-address, source-lan-address,
          source-wan-address, advice+connection-type+sync flags, identifier)

        - The sync payload uses 8 + 8 + 4 + 4 + 1 + 4 + 1 = 30 (time low, time high, modulo, offset,
          function, bits, prefix)
        """
        return (1500 - 60 - 8 - 51 - self._my_member.signature_length - 21 - 30) * 8

    def dispersy_claim_sync_bloom_filter(self, identifier):
        """
        Returns a (time_low, time_high, modulo, offset, bloom_filter) tuple or None.
        """
        # return self.dispersy_claim_sync_bloom_filter_right()
        # return self.dispersy_claim_sync_bloom_filter_50_50()
        return self.dispersy_claim_sync_bloom_filter_largest()
        # return self.dispersy_claim_sync_bloom_filter_simple()

    @runtime_duration_warning(0.5)
    def dispersy_claim_sync_bloom_filter_simple(self):
        bloom = BloomFilter(self.dispersy_sync_bloom_filter_bits, self.dispersy_sync_bloom_filter_error_rate, prefix=chr(int(random() * 256)))
        capacity = bloom.get_capacity(self.dispersy_sync_bloom_filter_error_rate)
        global_time = self.global_time

        desired_mean = global_time / 2.0
        lambd = 1.0 / desired_mean
        time_point = global_time - int(self._random.expovariate(lambd))
        if time_point < 1:
            time_point = int(self._random.random() * global_time)

        time_low = time_point - capacity / 2
        time_high = time_low + capacity

        if time_low < 1:
            time_low = 1
            time_high = capacity
            db_high = capacity

        elif time_high > global_time - capacity:
            time_low = max(1, global_time - capacity)
            time_high = self.acceptable_global_time
            db_high = global_time

        else:
            db_high = time_high

        bloom.add_keys(str(packet) for packet, in self._dispersy.database.execute(u"SELECT sync.packet FROM sync JOIN meta_message ON meta_message.id = sync.meta_message WHERE sync.community = ? AND meta_message.priority > 32 AND NOT sync.undone AND global_time BETWEEN ? AND ?", (self._database_id, time_low, db_high)))

        if __debug__:
            import sys
            print >> sys.stderr, "Syncing %d-%d, capacity = %d, pivot = %d"%(time_low, time_high, capacity, time_low)
        return (time_low, time_high, 1, 0, bloom)

    #choose a pivot, add all items capacity to the right. If too small, add items left of pivot
    @runtime_duration_warning(0.5)
    def dispersy_claim_sync_bloom_filter_right(self):
        bloom = BloomFilter(self.dispersy_sync_bloom_filter_bits, self.dispersy_sync_bloom_filter_error_rate, prefix=chr(int(random() * 256)))
        capacity = bloom.get_capacity(self.dispersy_sync_bloom_filter_error_rate)

        desired_mean = self.global_time / 2.0
        lambd = 1.0 / desired_mean
        from_gbtime = self.global_time - int(self._random.expovariate(lambd))
        if from_gbtime < 1:
            from_gbtime = int(self._random.random() * self.global_time)

        import sys
        #print >> sys.stderr, "Pivot", from_gbtime

        mostRecent = False
        if from_gbtime > 1:
            #use from_gbtime - 1 to include from_gbtime
            right,_ = self._select_and_fix(from_gbtime - 1, capacity, True)

            #we did not select enough items from right side, increase nr of items for left
            if len(right) < capacity:
                to_select = capacity - len(right)
                mostRecent = True

                left,_ = self._select_and_fix(from_gbtime, to_select, False)
                data = left + right
            else:
                data = right
        else:
            data,_ = self._select_and_fix(0, capacity, True)


        if len(data) > 0:
            if len(data) >= capacity:
                time_low = min(from_gbtime, data[0][0])

                if mostRecent:
                    time_high = self.acceptable_global_time
                else:
                    time_high = max(from_gbtime, data[-1][0])

            #we did not fill complete bloomfilter, assume we selected all items
            else:
                time_low = 1
                time_high = self.acceptable_global_time

            bloom.add_keys(str(packet) for _, packet in data)

            #print >> sys.stderr, "Syncing %d-%d, nr_packets = %d, capacity = %d, packets %d-%d"%(time_low, time_high, len(data), capacity, data[0][0], data[-1][0])

            return (time_low, time_high, 1, 0, bloom)
        return (1, self.acceptable_global_time, 1, 0, BloomFilter(8, 0.1, prefix='\x00'))

    #instead of pivot + capacity, divide capacity to have 50/50 divivion around pivot
    @runtime_duration_warning(0.5)
    def dispersy_claim_sync_bloom_filter_50_50(self):
        bloom = BloomFilter(self.dispersy_sync_bloom_filter_bits, self.dispersy_sync_bloom_filter_error_rate, prefix=chr(int(random() * 256)))
        capacity = bloom.get_capacity(self.dispersy_sync_bloom_filter_error_rate)

        desired_mean = self.global_time / 2.0
        lambd = 1.0 / desired_mean
        from_gbtime = self.global_time - int(self._random.expovariate(lambd))
        if from_gbtime < 1:
            from_gbtime = int(self._random.random() * self.global_time)

        # import sys
        #print >> sys.stderr, "Pivot", from_gbtime

        mostRecent = False
        leastRecent = False

        if from_gbtime > 1:
            to_select = capacity / 2

            #use from_gbtime - 1 to include from_gbtime
            right,_ = self._select_and_fix(from_gbtime - 1, to_select, True)

            #we did not select enough items from right side, increase nr of items for left
            if len(right) < to_select:
                to_select = capacity - len(right)
                mostRecent = True

            left,_ = self._select_and_fix(from_gbtime, to_select, False)

            #we did not select enough items from left side
            if len(left) < to_select:
                leastRecent = True

                #increase nr of items for right if we did select enough items on right side
                if len(right) >= to_select:
                    to_select = capacity - len(right) - len(left)
                    right = right + self._select_and_fix(right[-1][0], to_select, True)[0]
            data = left + right

        else:
            data,_ = self._select_and_fix(0, capacity, True)


        if len(data) > 0:
            if len(data) >= capacity:
                if leastRecent:
                    time_low = 1
                else:
                    time_low = min(from_gbtime, data[0][0])

                if mostRecent:
                    time_high = self.acceptable_global_time
                else:
                    time_high = max(from_gbtime, data[-1][0])

            #we did not fill complete bloomfilter, assume we selected all items
            else:
                time_low = 1
                time_high = self.acceptable_global_time

            bloom.add_keys(str(packet) for _, packet in data)

            #print >> sys.stderr, "Syncing %d-%d, nr_packets = %d, capacity = %d, packets %d-%d"%(time_low, time_high, len(data), capacity, data[0][0], data[-1][0])

            return (time_low, time_high, 1, 0, bloom)
        return (1, self.acceptable_global_time, 1, 0, BloomFilter(8, 0.1, prefix='\x00'))

    #instead of pivot + capacity, compare pivot - capacity and pivot + capacity to see which globaltime range is largest
    @runtime_duration_warning(0.5)
    def dispersy_claim_sync_bloom_filter_largest(self):
        if __debug__:
            t1 = time()

        syncable_messages = u", ".join(unicode(meta.database_id) for meta in self._meta_messages.itervalues() if isinstance(meta.distribution, SyncDistribution) and meta.distribution.priority > 32)
        if syncable_messages:
            if __debug__:
                t2 = time()

            acceptable_global_time = self.acceptable_global_time
            bloom = BloomFilter(self.dispersy_sync_bloom_filter_bits, self.dispersy_sync_bloom_filter_error_rate, prefix=chr(int(random() * 256)))
            capacity = bloom.get_capacity(self.dispersy_sync_bloom_filter_error_rate)

            desired_mean = self.global_time / 2.0
            lambd = 1.0 / desired_mean
            from_gbtime = self.global_time - int(self._random.expovariate(lambd))
            if from_gbtime < 1:
                from_gbtime = int(self._random.random() * self.global_time)

            if from_gbtime > 1 and self._nrsyncpackets >= capacity:
                #use from_gbtime -1/+1 to include from_gbtime
                right, rightdata = self._select_bloomfilter_range(syncable_messages, from_gbtime -1, capacity, True)

                #if right did not get to capacity, then we have less than capacity items in the database
                #skip left
                if right[2] == capacity:
                    left, leftdata = self._select_bloomfilter_range(syncable_messages, from_gbtime + 1, capacity, False)
                    left_range = (left[1] or self.global_time) - left[0]
                    right_range = (right[1] or self.global_time) - right[0]

                    if left_range > right_range:
                        bloomfilter_range = left
                        data = leftdata
                    else:
                        bloomfilter_range = right
                        data = rightdata

                    if __debug__:
                        dprint(self.cid.encode("HEX"), " bloomfilterrange left", left, " right", right, "left" if left_range > right_range else "right")
                else:
                    bloomfilter_range = right
                    data = rightdata

                if __debug__:
                    t3 = time()
            else:
                if __debug__:
                    t3 = time()

                bloomfilter_range = [1, acceptable_global_time]

                data, fixed = self._select_and_fix(syncable_messages, 0, capacity, True)
                if len(data) > 0 and fixed:
                    bloomfilter_range[1] = data[-1][0]
                    self._nrsyncpackets = capacity + 1

            if __debug__:
                t4 = time()

            if len(data) > 0:
                bloom.add_keys(str(packet) for _, packet in data)

                if __debug__:
                    dprint(self.cid.encode("HEX"), " syncing %d-%d, nr_packets = %d, capacity = %d, packets %d-%d, pivot = %d"%(bloomfilter_range[0], bloomfilter_range[1], len(data), capacity, data[0][0], data[-1][0], from_gbtime))
                    dprint(self.cid.encode("HEX"), " took %f (fakejoin %f, rangeselect %f, dataselect %f, bloomfill, %f"%(time()-t1, t2-t1, t3-t2, t4-t3, time()-t4))

                return (min(bloomfilter_range[0], acceptable_global_time), min(bloomfilter_range[1], acceptable_global_time), 1, 0, bloom)

            if __debug__:
                dprint(self.cid.encode("HEX"), " no messages to sync")

        elif __debug__:
            dprint(self.cid.encode("HEX"), " NOT syncing no syncable messages")
        return (1, acceptable_global_time, 1, 0, BloomFilter(8, 0.1, prefix='\x00'))

    #instead of pivot + capacity, compare pivot - capacity and pivot + capacity to see which globaltime range is largest
    @runtime_duration_warning(0.5)
    def dispersy_claim_sync_bloom_filter_modulo(self):
        syncable_messages = u", ".join(unicode(meta.database_id) for meta in self._meta_messages.itervalues() if isinstance(meta.distribution, SyncDistribution) and meta.distribution.priority > 32)
        if syncable_messages:
            bloom = BloomFilter(self.dispersy_sync_bloom_filter_bits, self.dispersy_sync_bloom_filter_error_rate, prefix=chr(int(random() * 256)))
            capacity = bloom.get_capacity(self.dispersy_sync_bloom_filter_error_rate)

            self._nrsyncpackets = list(self._dispersy.database.execute(u"SELECT count(*) FROM sync WHERE meta_message IN (%s) AND undone = 0 LIMIT 1" % (syncable_messages)))[0][0]
            modulo = int(ceil(self._nrsyncpackets / float(capacity)))
            if modulo > 1:
                offset = randint(0, modulo-1)
            else:
                offset = 0
                modulo = 1

            packets = list(str(packet) for packet, in self._dispersy.database.execute(u"SELECT sync.packet FROM sync WHERE meta_message IN (%s) AND sync.undone = 0 AND sync.global_time > 0 AND (sync.global_time + ?) %% ? = 0" % syncable_messages, (offset, modulo)))
            bloom.add_keys(packets)

            if __debug__:
                dprint(self.cid.encode("HEX"), " syncing %d-%d, nr_packets = %d, capacity = %d, totalnr = %d"%(modulo, offset, self._nrsyncpackets, capacity, self._nrsyncpackets))

            return (1, self.acceptable_global_time, modulo, offset, bloom)

        elif __debug__:
            dprint(self.cid.encode("HEX"), " NOT syncing no syncable messages")
        return (1, self.acceptable_global_time, 1, 0, BloomFilter(8, 0.1, prefix='\x00'))


    def _select_and_fix(self, syncable_messages, global_time, to_select, higher = True):
        assert isinstance(syncable_messages, unicode)
        if higher:
            data = list(self._dispersy.database.execute(u"SELECT global_time, packet FROM sync WHERE meta_message IN (%s) AND undone = 0 AND global_time > ? ORDER BY global_time ASC LIMIT ?" % (syncable_messages),
                                                    (global_time, to_select + 1)))
        else:
            data = list(self._dispersy.database.execute(u"SELECT global_time, packet FROM sync WHERE meta_message IN (%s) AND undone = 0 AND global_time < ? ORDER BY global_time DESC LIMIT ?" % (syncable_messages),
                                                    (global_time, to_select + 1)))

        fixed = False
        if len(data) > to_select:
            fixed = True

            #if last 2 packets are equal, then we need to drop those
            global_time = data[-1][0]
            del data[-1]
            while data and data[-1][0] == global_time:
                del data[-1]

        if not higher:
            data.reverse()

        return data, fixed

    def _select_bloomfilter_range(self, syncable_messages, global_time, to_select, higher = True):
        data, fixed = self._select_and_fix(syncable_messages, global_time, to_select, higher)

        lowerfixed = True
        higherfixed = True

        #if we selected less than to_select
        if len(data) < to_select:
            #calculate how many still remain
            to_select = to_select - len(data)
            if to_select > 25:
                if higher:
                    lowerdata, lowerfixed = self._select_and_fix(syncable_messages, global_time + 1, to_select, False)
                    data = lowerdata + data
                else:
                    higherdata, higherfixed = self._select_and_fix(syncable_messages, global_time - 1, to_select, True)
                    data = data + higherdata

        bloomfilter_range = [data[0][0], data[-1][0], len(data)]
        #we can use the global_time as a min or max value for lower and upper bound
        if higher:
            #we selected items higher than global_time, make sure bloomfilter_range[0] is at least as low a global_time + 1
            #we select all items higher than global_time, thus all items global_time + 1 are included
            bloomfilter_range[0] = min(bloomfilter_range[0], global_time + 1)

            #if not fixed and higher, then we have selected up to all know packets
            if not fixed:
                bloomfilter_range[1] = self.acceptable_global_time
            if not lowerfixed:
                bloomfilter_range[0] = 1
        else:
            #we selected items lower than global_time, make sure bloomfilter_range[1] is at least as high as global_time -1
            #we select all items lower than global_time, thus all items global_time - 1 are included
            bloomfilter_range[1] = max(bloomfilter_range[1], global_time - 1)

            if not fixed:
                bloomfilter_range[0] = 1
            if not higherfixed:
                bloomfilter_range[1] = self.acceptable_global_time

        return bloomfilter_range, data

    # def dispersy_claim_sync_bloom_filter(self, identifier):
    #     """
    #     Returns a (time_low, time_high, bloom_filter) tuple or None.
    #     """
    #     count, = self._dispersy.database.execute(u"SELECT COUNT(1) FROM sync JOIN meta_message ON meta_message.id = sync.meta_message WHERE sync.community = ? AND meta_message.priority > 32", (self._database_id,)).next()
    #     if count:
    #         bloom = BloomFilter(self.dispersy_sync_bloom_filter_bits, self.dispersy_sync_bloom_filter_error_rate, prefix=chr(int(random() * 256)))
    #         capacity = bloom.get_capacity(self.dispersy_sync_bloom_filter_error_rate)
    #         ranges = int(ceil(1.0 * count / capacity))

    #         desired_mean = ranges / 2.0
    #         lambd = 1.0 / desired_mean
    #         range_ = ranges - int(ceil(expovariate(lambd)))
    #         # RANGE_ < 0 is possible when the exponential function returns a very large number (least likely)
    #         # RANGE_ = 0 is the oldest time bloomfilter_range (less likely)
    #         # RANGE_ = RANGES - 1 is the highest time bloomfilter_range (more likely)

    #         if range_ < 0:
    #             # pick uniform randomly
    #             range_ = int(random() * ranges)

    #         if range_ == ranges - 1:
    #             # the chosen bloomfilter_range is to small to fill an entire bloom filter.  adjust the offset
    #             # accordingly
    #             offset = max(0, count - capacity + 1)

    #         else:
    #             offset = range_ * capacity

    #         # get the time bloomfilter_range associated to the offset
    #         try:
    #             time_low, time_high = self._dispersy.database.execute(u"SELECT MIN(sync.global_time), MAX(sync.global_time) FROM sync JOIN meta_message ON meta_message.id = sync.meta_message WHERE sync.community = ? AND meta_message.priority > 32 ORDER BY sync.global_time LIMIT ? OFFSET ?",
    #                                                                   (self._database_id, capacity, offset)).next()
    #         except:
    #             dprint("count: ", count, " capacity: ", capacity, " bloomfilter_range: ", range_, " ranges: ", ranges, " offset: ", offset, force=1)
    #             assert False

    #         if __debug__ and self.get_classification() == u"ChannelCommunity":
    #             low, high = self._dispersy.database.execute(u"SELECT MIN(sync.global_time), MAX(sync.global_time) FROM sync JOIN meta_message ON meta_message.id = sync.meta_message WHERE sync.community = ? AND meta_message.priority > 32",
    #                                                         (self._database_id,)).next()
    #             dprint("bloomfilter_range: ", range_, " ranges: ", ranges, " offset: ", offset, " time: [", time_low, ":", time_high, "] in-db: [", low, ":", high, "]", force=1)

    #         assert isinstance(time_low, (int, long))
    #         assert isinstance(time_high, (int, long))

    #         assert 0 < ranges
    #         assert 0 <= range_ < ranges
    #         assert ranges == 1 and range_ == 0 or ranges > 1
    #         assert 0 <= offset

    #         # get all the data associated to the time bloomfilter_range
    #         counter = 0
    #         for packet, in self._dispersy.database.execute(u"SELECT sync.packet FROM sync JOIN meta_message ON meta_message.id = sync.meta_message WHERE sync.community = ? AND meta_message.priority > 32 AND sync.global_time BETWEEN ? AND ?",
    #                                                        (self._database_id, time_low, time_high)):
    #             bloom.add(str(packet))
    #             counter += 1

    #         if range_ == 0:
    #             time_low = 1

    #         if range_ == ranges - 1:
    #             time_high = 0

    #         if __debug__ and self.get_classification() == u"ChannelCommunity":
    #             dprint("off: ", offset, " cap: ", capacity, " count: ", counter, "/", count, " time: [", time_low, ":", time_high, "]", force=1)

    #         # if __debug__:
    #         #     if len(data) > 1:
    #         #         low, high = self._dispersy.database.execute(u"SELECT MIN(sync.global_time), MAX(sync.global_time) FROM sync JOIN meta_message ON meta_message.id = sync.meta_message WHERE sync.community = ? AND meta_message.priority > 32",
    #         #                                                     (self._database_id,)).next()
    #         #         dprint(self.cid.encode("HEX"), " syncing <<", data[0][0], " <", data[1][0], "-", data[-2][0], "> ", data[-1][0], ">> sync:[", time_low, ":", time_high, "] db:[", low, ":", high, "] len:", len(data), " cap:", capacity)

    #         return (time_low, time_high, bloom)

    #     return (1, 0, BloomFilter(8, 0.1, prefix='\x00'))

    @property
    def dispersy_sync_response_limit(self):
        """
        The maximum number of bytes to send back per received dispersy-sync message.
        @rtype: int
        """
        return 5 * 1025

    @property
    def dispersy_missing_sequence_response_limit(self):
        """
        The maximum number of bytes to send back per received dispersy-missing-sequence message.
        @rtype: (int, int)
        """
        return 10 * 1025

    @property
    def dispersy_acceptable_global_time_range(self):
        return 10000

    @property
    def cid(self):
        """
        The 20 byte sha1 digest of the public master key, in other words: the community identifier.
        @rtype: string
        """
        return self._cid

    @property
    def database_id(self):
        """
        The number used to identify this community in the local Dispersy database.
        @rtype: int or long
        """
        return self._database_id

    @property
    def database_version(self):
        return self._database_version

    @property
    def master_member(self):
        """
        The community Member instance.
        @rtype: Member
        """
        return self._master_member

    @property
    def my_member(self):
        """
        Our own Member instance that is used to sign the messages that we create.
        @rtype: Member
        """
        return self._my_member

    @property
    def dispersy(self):
        """
        The Dispersy instance.
        @rtype: Dispersy
        """
        return self._dispersy

    @property
    def timeline(self):
        """
        The Timeline instance.
        @rtype: Timeline
        """
        return self._timeline

    @property
    def global_time(self):
        """
        The most highest global time that we have stored in the database.
        @rtype: int or long
        """
        return max(1, self._global_time)

    @property
    def acceptable_global_time(self):
        """
        The highest global time that we will accept for incoming messages that need to be stored in
        the database.

        We follow one of two strategies:

        When we have more than 5 candidates (i.e. we have more than 5 opinions about what the
        global_time should be) we will use its median + dispersy_acceptable_global_time_range.

        Otherwise we will not trust the candidate's opinions and use our own global time (obtained
        from the highest global time in the database) + dispersy_acceptable_global_time_range.

        @rtype: int or long
        """
        def acceptable_global_time_helper():
            options = sorted(global_time for global_time in (candidate.get_global_time(self) for candidate in self._dispersy.candidates if candidate.in_community(self, now) and candidate.is_any_active(now)) if global_time > 0)

            if len(options) > 5:
                # note: officially when the number of options is even, the median is the average between the
                # two 'middle' options.  in our case we simply round down the 'middle' option
                median_global_time = options[len(options) / 2]

            else:
                median_global_time = 0

            # 07/05/12 Boudewijn: for an unknown reason values larger than 2^63-1 cause overflow
            # exceptions in the sqlite3 wrapper
            return min(max(self._global_time, median_global_time) + self.dispersy_acceptable_global_time_range, 2**63-1)

        # get opinions from all active candidates
        now = time()
        if self._acceptable_global_time_deadline < now:
            self._acceptable_global_time_cache = acceptable_global_time_helper()
            self._acceptable_global_time_deadline = now + 5.0
        return self._acceptable_global_time_cache

    def unload_community(self):
        """
        Unload a single community.
        """
        # remove all pending callbacks
        for id_ in self._pending_callbacks:
            self._dispersy.callback.unregister(id_)
        self._pending_callbacks = []

        self._dispersy.detach_community(self)

    def claim_global_time(self):
        """
        Increments the current global time by one and returns this value.
        @rtype: int or long
        """
        self._global_time += 1
        if __debug__: dprint(self._global_time)
        return self._global_time

    def update_global_time(self, global_time):
        """
        Increase the local global time if the given GLOBAL_TIME is larger.
        """
        if __debug__:
            previous = self._global_time
            new = max(self._global_time, global_time)
            level = "warning" if new - previous >= 100 else "normal"
            dprint(previous, " -> ", new, level=level)
        self._global_time = max(self._global_time, global_time)

    def dispersy_check_database(self):
        """
        Called each time after the community is loaded and attached to Dispersy.
        """
        self._database_version = self._dispersy.database.check_community_database(self, self._database_version)

    def get_member(self, public_key):
        """
        Returns a Member instance associated with public_key.

        since we have the public_key, we can create this user when it didn't already exist.  Hence,
        this method always succeeds.

        @param public_key: The public key of the member we want to obtain.
        @type public_key: string

        @return: The Member instance associated with public_key.
        @rtype: Member

        @note: This returns -any- Member, it may not be a member that is part of this community.

        @todo: Since this method returns Members that are not specifically bound to any community,
         this method should be moved to Dispersy
        """
        if __debug__: dprint("deprecated.  please use Dispersy.get_member", level="warning")
        return self._dispersy.get_member(public_key)

    def get_members_from_id(self, mid):
        """
        Returns zero or more Member instances associated with mid, where mid is the sha1 digest of a
        member public key.

        As we are using only 20 bytes to represent the actual member public key, this method may
        return multiple possible Member instances.  In this case, other ways must be used to figure
        out the correct Member instance.  For instance: if a signature or encryption is available,
        all Member instances could be used, but only one can succeed in verifying or decrypting.

        Since we may not have the public key associated to MID, this method may return an empty
        list.  In such a case it is sometimes possible to DelayPacketByMissingMember to obtain the
        public key.

        @param mid: The 20 byte sha1 digest indicating a member.
        @type mid: string

        @return: A list containing zero or more Member instances.
        @rtype: [Member]

        @note: This returns -any- Member, it may not be a member that is part of this community.

        @todo: Since this method returns Members that are not specifically bound to any community,
         this method should be moved to Dispersy
        """
        if __debug__: dprint("deprecated.  please use Dispersy.get_members_from_id", level="warning")
        return self._dispersy.get_members_from_id(mid)

    def get_conversion(self, prefix=None):
        """
        returns the conversion associated with prefix.

        prefix is an optional 22 byte sting.  Where the first byte is
        the dispersy version, the second byte is the community version
        and the last 20 bytes is the community identifier.

        When no prefix is given, i.e. prefix is None, then the default Conversion is returned.
        Conversions are assigned to a community using add_conversion().

        @param prefix: Optional prefix indicating a conversion.
        @type prefix: string

        @return A Conversion instance indicated by prefix or the default one.
        @rtype: Conversion
        """
        assert prefix is None or isinstance(prefix, str)
        assert prefix is None or len(prefix) == 22
        return self._conversions[prefix]

    def add_conversion(self, conversion, default=False):
        """
        Add a Conversion to the Community.

        A conversion instance converts between the internal Message structure and the on-the-wire
        message.

        When default is True the conversion is set to be the default conversion.  The default
        conversion is used (by default) when a message is implemented and no prefix is given.

        @param conversion: The new conversion instance.
        @type conversion: Conversion

        @param default: Indicating if this is to become the default conversion.
        @type default: bool
        """
        if __debug__:
            from conversion import Conversion
        assert isinstance(conversion, Conversion)
        assert isinstance(default, bool)
        assert not conversion.prefix in self._conversions
        if default:
            self._conversions[None] = conversion
        self._conversions[conversion.prefix] = conversion

    @documentation(Dispersy.take_step)
    def dispersy_take_step(self, allow_sync):
        return self._dispersy.take_step(self, allow_sync)

    @documentation(Dispersy.get_message)
    def get_dispersy_message(self, member, global_time):
        return self._dispersy.get_message(self, member, global_time)

    @documentation(Dispersy.create_authorize)
    def create_dispersy_authorize(self, permission_triplets, sign_with_master=False, store=True, update=True, forward=True):
        return self._dispersy.create_authorize(self, permission_triplets, sign_with_master, store, update, forward)

    @documentation(Dispersy.create_revoke)
    def create_dispersy_revoke(self, permission_triplets, sign_with_master=False, store=True, update=True, forward=True):
        return self._dispersy.create_revoke(self, permission_triplets, sign_with_master, store, update, forward)

    @documentation(Dispersy.create_undo)
    def create_dispersy_undo(self, message, sign_with_master=False, store=True, update=True, forward=True):
        return self._dispersy.create_undo(self, message, sign_with_master, store, update, forward)

    @documentation(Dispersy.create_identity)
    def create_dispersy_identity(self, sign_with_master=False, store=True, update=True):
        return self._dispersy.create_identity(self, sign_with_master, store, update)

    @documentation(Dispersy.create_signature_request)
    def create_dispersy_signature_request(self, message, response_func, response_args=(), timeout=10.0, forward=True):
        return self._dispersy.create_signature_request(self, message, response_func, response_args, timeout, forward)

    @documentation(Dispersy.create_destroy_community)
    def create_dispersy_destroy_community(self, degree, sign_with_master=False, store=True, update=True, forward=True):
        return self._dispersy.create_destroy_community(self, degree, sign_with_master, store, update, forward)

    @documentation(Dispersy.create_dynamic_settings)
    def create_dispersy_dynamic_settings(self, policies, sign_with_master=False, store=True, update=True, forward=True):
        return self._dispersy.create_dynamic_settings(self, policies, sign_with_master, store, update, forward)

    @documentation(Dispersy.create_introduction_request)
    def create_introduction_request(self, candidate, allow_sync):
        return self._dispersy.create_introduction_request(self, candidate, allow_sync)

    def dispersy_on_dynamic_settings(self, messages, initializing=False):
        return self._dispersy.on_dynamic_settings(self, messages, initializing)

    def dispersy_cleanup_community(self, message):
        """
        A dispersy-destroy-community message is received.

        Once a community is destroyed, it must be reclassified to ensure that it is not loaded in
        its regular form.  This method returns the class that the community will be reclassified
        into.  The default is either the SoftKilledCommunity or the HardKilledCommunity class,
        depending on the received dispersy-destroy-community message.

        Depending on the degree of the destroy message, we will need to cleanup in different ways.

         - soft-kill: The community is frozen.  Dispersy will retain the data it has obtained.
           However, no messages beyond the global-time of the dispersy-destroy-community message
           will be accepted.  Responses to dispersy-sync messages will be send like normal.

         - hard-kill: The community is destroyed.  Dispersy will throw away everything except the
           dispersy-destroy-community message and the authorize chain that is required to verify
           this message.  The community should also remove all its data and cleanup as much as
           possible.

        Similar to other on_... methods, this method may raise a DropMessage exception.  In this
        case the message will be ignored and no data is removed.  However, each dispersy-sync that
        is sent is likely to result in the same dispersy-destroy-community message to be received.

        @param address: The address from where we received this message.
        @type address: (string, int)

        @param message: The received message.
        @type message: Message.Implementation

        @rtype: Community class
        """
        # override to implement community cleanup
        if message.payload.is_soft_kill:
            raise NotImplementedError()

        elif message.payload.is_hard_kill:
            return HardKilledCommunity

    def dispersy_malicious_member_detected(self, member, packets):
        """
        Proof has been found that MEMBER is malicious

        @param member: The malicious member.
        @type member: Member

        @param packets: One or more packets proving that the member is malicious.  All packets must
         be associated to the same community.
        @type packets: [Packet]
        """
        pass

    def get_meta_message(self, name):
        """
        Returns the meta message by its name.

        @param name: The name of the message.
        @type name: unicode

        @return: The meta message.
        @rtype: Message

        @raise KeyError: When there is no meta message by that name.
        """
        assert isinstance(name, unicode)
        if __debug__:
            if not name in self._meta_messages:
                dprint("this community does not support the ", name, " message")
        return self._meta_messages[name]

    def get_meta_messages(self):
        """
        Returns all meta messages.

        @return: The meta messages.
        @rtype: [Message]
        """
        return self._meta_messages.values()

    def initiate_meta_messages(self):
        """
        Create the meta messages for one community instance.

        This method is called once for each community when it is created.  The resulting meta
        messages can be obtained by either get_meta_message(name) or get_meta_messages().

        To distinct the meta messages that the community provides from those that Dispersy provides,
        none of the messages may have a name that starts with 'dispersy-'.

        @return: The new meta messages.
        @rtype: [Message]
        """
        raise NotImplementedError()

    def initiate_conversions(self):
        """
        Create the Conversion instances for this community instance.

        This method is called once for each community when it is created.  The resulting Conversion
        instances can be obtained using the get_conversion(prefix) method.

        Returns a list with all Conversion instances that this community will support.  The last
        item in the list will be used as the default conversion.

        @rtype: [Conversion]
        """
        raise NotImplementedError()

class HardKilledCommunity(Community):
    def __init__(self, *args, **kargs):
        super(HardKilledCommunity, self).__init__(*args, **kargs)

        destroy_message_id = self._meta_messages[u"dispersy-destroy-community"].database_id
        try:
            packet, = self._dispersy.database.execute(u"SELECT packet FROM sync WHERE meta_message = ? LIMIT 1", (destroy_message_id,)).next()
        except StopIteration:
            if __debug__: dprint("unable to locate the dispersy-destroy-community message", level="error")
            self._destroy_community_packet = ""
        else:
            self._destroy_community_packet = str(packet)

    def _initialize_meta_messages(self):
        super(HardKilledCommunity, self)._initialize_meta_messages()

        # remove all messages that we no longer need
        meta_messages = self._meta_messages
        self._meta_messages = {}
        for name in [u"dispersy-introduction-request",
                     # u"dispersy-introduction-response",
                     u"dispersy-identity",
                     u"dispersy-missing-identity",
                     u"dispersy-missing-proof",
                     u"dispersy-destroy-community"]:
            self._meta_messages[name] = meta_messages[name]

        # replace introduction_request behavior
        self._meta_messages[u"dispersy-introduction-request"]._handle_callback = self.dispersy_on_introduction_request

    @property
    def dispersy_enable_candidate_walker(self):
        # disable candidate walker
        return False

    @property
    def dispersy_enable_candidate_walker_responses(self):
        # enable walker responses
        return True

    def initiate_meta_messages(self):
        # there are no community messages
        return []

    def initiate_conversions(self):
        # TODO we will not be able to use this conversion because the community version will not
        # match
        return [DefaultConversion(self)]

    def get_conversion(self, prefix=None):
        if not prefix in self._conversions:

            # the dispersy version MUST BE available.  Currently we
            # only support \x00: BinaryConversion
            if prefix[0] == "\x00":
                self._conversions[prefix] = BinaryConversion(self, prefix[1])

            else:
                raise KeyError("Unknown conversion")

            # use highest version as default
            if None in self._conversions:
                if self._conversions[None].version < self._conversions[prefix].version:
                    self._conversions[None] = self._conversions[prefix]
            else:
                self._conversions[None] = self._conversions[prefix]

        return self._conversions[prefix]

    def dispersy_on_introduction_request(self, messages):
        self._dispersy.endpoint.send([message.candidate for message in messages], [self._destroy_community_packet])
