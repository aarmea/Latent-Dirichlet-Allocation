# Fri 19 Nov 2010 11:50:56 EST
# Set of helper functions to read, write and call David Newman's
# topic model code: http://www.ics.uci.edu/~newman/code/topicmodel/


import sys, os
import logging
import math

import numpy

# from scipy import sparse


# needed?
PROJECT_PATH=os.path.realpath(os.path.join(os.path.dirname(__file__),".."))
PACK_DIR=os.path.realpath(os.path.join(os.path.dirname(__file__),"packs/"))
RUN_ROOT = os.path.join(PROJECT_PATH, "data/runs/")
#RUN_DIR="../data/runs/run2_first_test/"



logger = logging.getLogger("newmanlib")
logger.setLevel(logging.INFO)




# Portions of the code is heavily inspired by:
# Copyright (C) 2010 Radim Rehurek <radimrehurek@seznam.cz>
# Licensed under the GNU LGPL v2.1 - http://www.gnu.org/licenses/lgpl.html

class NewmanWriter(object):
    """
    Store corpus into a file docword.txt in the Dave Newman's sparse matrix format.

    used via static method writeCorpus as follows:
        NewmanWriter.writeCorpus(fname, corpus)
        where fname is either a file-like object or a string containing the filename,
        and corpus is of the type [[(,)]]

    """

    def __init__(self, fname):
        self.fname = fname

        tmp = open(self.fname, 'w') # reset/create the target file
        tmp.close()
        self.fout = open(self.fname, 'rb+') # open for both reading and writing
        self.headersWritten = False


    def writeHeaders(self, numDocs, numTerms, numNnz):
        import string   # needed for padding left to 30 chars
        if numNnz < 0:
            # we don't know the matrix shape/density yet, so only log a general line
            logger.info("saving sparse matrix to %s" % self.fname)
            self.fout.write(' ' * 30 + '\n') # save three newlines for headers
            self.fout.write(' ' * 30 + '\n') #
            self.fout.write(' ' * 30 + '\n') # 30 digits must be enough even for the
                                             #  most avid Megalomane
        else:
            logger.info("saving sparse %sx%s matrix with %i non-zero entries to %s" %
                         (numDocs, numTerms, numNnz, self.fname))
            self.fout.write(string.ljust('%s' % numDocs, 30) +'\n')
            self.fout.write(string.ljust('%s' % numTerms, 30) +'\n')
            self.fout.write(string.ljust('%s' % numNnz, 30) +'\n')

        self.lastDocNo = -1
        self.headersWritten = True


    def realHeaders(self, numDocs, numTerms, numNnz):
        import string   # needed for padding left to 30 chars
        logger.info("writing the real headers now --  sparse %sx%s matrix with %i non-zero entries to %s" %
                         (numDocs, numTerms, numNnz, self.fname))
        self.fout.seek(0)
        self.fout.write(string.ljust('%s' % numDocs, 30) + '\n')
        self.fout.write(string.ljust('%s' % numTerms, 30) + '\n')
        self.fout.write(string.ljust('%s' % numNnz, 30) + '\n')



    def writeVector(self, docNo, vector):
        """
        Write a single sparse vector to the file.

        Sparse vector is any iterable yielding (field id, field value) pairs.
        """
        assert self.headersWritten, "must write Matrix Market file headers before writing data!"
        assert self.lastDocNo < docNo, "documents %i and %i not in sequential order!" % (self.lastDocNo, docNo)
        for termId, weight in sorted(vector): # write term ids in sorted order
            if weight == 0:
                # to ensure len(doc) does what is expected, there must not be any zero elements in the sparse document
                raise ValueError("zero weights not allowed in sparse documents; check your document generator")
            #self.fout.write("%i %i %s\n" % (docNo + 1, termId + 1, weight)) # +1 because MM format starts counting from 1
            # Newman reader function int **read_sparse(char *fname, int *nr_, int *nc_)
            # is looking for a %d in the file so I will coerse to int
            self.fout.write("%i %i %i\n" % (docNo + 1, termId + 1, int(weight))) # +1 because MM format starts counting from 1
        self.lastDocNo = docNo


    @staticmethod
    def writeCorpus(fname, corpus, progressCnt = 10000):
        """
        Save the vector space representation of an entire corpus to disk.

        Note that the documents are processed one at a time, so the whole corpus
        is allowed to be larger than the available RAM.
        """
        mw = NewmanWriter(fname)

        # write empty headers to the file (with enough space to be overwritten later)
        mw.writeHeaders(-1, -1, -1) # will print three rows of 30 spaces each
                                    # need to reserve space for when we have the total NZ count

        # calculate necessary header info (nnz elements, num terms, num docs) while writing out vectors
        numTerms = numNnz = 0
        docNo = -1

        for docNo, bow in enumerate(corpus):
            if docNo % progressCnt == 0:
                logger.info("PROGRESS: saving document #%i" % docNo)
            if len(bow) > 0:
                numTerms = max(numTerms, 1 + max(wordId for wordId, val in bow))
                numNnz += len(bow)
            mw.writeVector(docNo, bow)
        numDocs = docNo + 1

        if numDocs * numTerms != 0:
            logger.info("saved %ix%i matrix, density=%.3f%% (%i/%i)" %
                         (numDocs, numTerms,
                          100.0 * numNnz / (numDocs * numTerms),
                          numNnz,
                          numDocs * numTerms))

        # now write proper headers, by seeking and overwriting a part of the file
        mw.realHeaders(numDocs, numTerms, numNnz)

        mw.close()


    def __del__(self):
        """
        Automatic destructor which closes the underlying file.

        There must be no circular references contained in the object for __del__
        to work! Closing the file explicitly via the close() method is preferred
        and safer.
        """
        self.close() # does nothing if called twice (on an already closed file), so no worries


    def close(self):
        logging.debug("closing %s" % self.fname)
        self.fout.close()
#endclass NewanWriter







class NewmanReader(object):
    """
    Wrap a term-document matrix on disk (in Dave Newman's sparse matrix format), and present it
    as an object which supports iteration over the documents.

    Note that the file is read into memory one document at a time, not the whole
    matrix at once (unlike scipy.io.mmread). This allows for representing corpora
    which are larger than the available RAM.
    """


    def __init__(self, input, transposed=True):

        """
        Initialize the matrix reader.

        `input` is either a string (file path) or a file-like object that supports
        `seek(0)` (e.g. gzip.GzipFile, bz2.BZ2File).
        The contents are expected to be in the following format:

           numDocs
           numTerms
           numElements
           i j count(j in i)
           ...
           ...

        The i index the documents (1 based indexing),
        j stands for the wordid (j=1="aardvark", j=2="abs", ...  j=MaxJ="zulu")
        the third column contains the count of how many times word j appears in document i.

        The number of lines in the file should be numEntries + 3.
        """

        logger.info("initializing Newman reader from %s" % input)

        self.input, self.transposed = input, transposed
        if isinstance(input, basestring):
            input = open(input)

        # get the header information
        self.numDocs = self.numTerms = self.numElements = 0
        MaxI = input.next().strip()
        MaxJ = input.next().strip()
        NumRows = input.next().strip()

        self.numDocs, self.numTerms, self.numElements = map(int, [MaxI,MaxJ,NumRows] )

        if not self.transposed:
            self.numDocs, self.numTerms = self.numTerms, self.numDocs

        logger.info("accepted corpus with %i documents, %i terms, %i non-zero entries" %
                     (self.numDocs, self.numTerms, self.numElements))

    def __len__(self):
        return self.numDocs

    def __str__(self):
        return ("MmCorpus(%i documents, %i features, %i non-zero entries)" %
                (self.numDocs, self.numTerms, self.numElements))

    def __iter__(self):
        """
        Iteratively yield vectors from the underlying file, in the format (rowNo, vector),
        where vector is a list of (colId, value) 2-tuples.

        Note that the total number of vectors returned is always equal to the
        number of rows specified in the header; empty documents are inserted and
        yielded where appropriate, even if they are not explicitly stored in the
        Matrix Market file.
        """
        if isinstance(self.input, basestring):
            fin = open(self.input)
        else:
            fin = self.input
            fin.seek(0)

        # skip 3 lines of headers
        fin.next()
        fin.next()
        fin.next()

        prevId = -1
        for line in fin:
            docId, termId, val = line.split()
            if not self.transposed:
                termId, docId = docId, termId
            docId, termId, val = int(docId) - 1, int(termId) - 1, float(val) # -1 because matrix market indexes are 1-based => convert to 0-based
            assert prevId <= docId, "matrix columns must come in ascending order"
            if docId != prevId:
                # change of document: return the document read so far (its id is prevId)
                if prevId >= 0:
                    yield prevId, document

                # return implicit (empty) documents between previous id and new id
                # too, to keep consistent document numbering and corpus length
                for prevId in xrange(prevId + 1, docId):
                    yield prevId, []

                # from now on start adding fields to a new document, with a new id
                prevId = docId
                document = []

            document.append((termId, val,)) # add another field to the current document

        # handle the last document, as a special case
        if prevId >= 0:
            yield prevId, document
        for prevId in xrange(prevId + 1, self.numDocs):
            yield prevId, []


#endclas NewmanReader









############################## ############################## ##############################
############################## ############################## ##############################
############################## ############################## ##############################
############################## ############################## ##############################


class NewmanLdaModel(object):
    """
    This is the the main class for the LDA topic model functionnality

    attrinbutes:
        N           : total number of words in documet collection
        T           : number of topics in model
        documents   : reference to a DocumentColleciton object
        D           : len(documents)
        vocab       : ref to Vacabulary object
        W           : len(vocab)

        phi         : topic-word distribution
                      size: WxT
                      alias: prob_w_given_t
        theta       : topic-document distibution
                      size: TxD
                      alias: prob_t_given_d
        z           : the topic assignment
                      size: ?
        topics      : array of size T with short descriptions for each of the topics
                      ['physics', 'chemistry', ... , 'general science']


    methods:
        __init__ constuctor ... see below
        train(method)
        query(queryDocCol, method)

    """

    def __init__(self): #, documents=None, T=None, vocab=None):
        """
        must give a DocumentCollection object upon creation and T # topics
        """

        self.T=None
        self.documents = None


        # trained / non-trained
        self.is_trained = False


#    def __init__(self,rundir):
#        self.trained = False
#        self.path = '?????'



    def fromDocumentCollection(self, documents=None, T=None, vocab=None):
        pass

    def loadFromPickledDict(self, fileobj):
        """Loads the TopicModel from a cPickle file-like object """
        pass

    def loadFromJson(self):
        """Loads the TopicModel from a json file"""
        pass


    def train(self, method):
        """ run the training method on the TopicModel
            allowed values are:
            NewmanGibbs
            (soon) AndrzejewskiCVB
            """
        pass












def loadsparsemat(filename):
    """ Load a Nweman sparse matrix from file `filename` """
    indata = open(filename).readlines()
    NROWS=int(indata[0].strip() )       # first line is W
    NCOLS=int(indata[1].strip() )       # T
    nCols =int(indata[2].strip() )
    cols = indata[3:]
    assert( len(cols) == nCols)

    wp = numpy.zeros([NROWS,NCOLS])       # undormalized word dopic \beta distr.
    for line in cols:
        if len(line)>0:
            [i,j,d]= line.split()
            wp[int(i)-1,int(j)-1] = d
    return wp




def conv_Ndt_to_theta(input):
    """
    converts the topic counts in documents
    to a probability distibution
      p(t|d)
    rows are documents
    columns are topic proportions
    """

    numDocs,numT = input.shape

    input = numpy.array( input, dtype=numpy.float )

    normalizer = 1.0/numpy.sum(input,1)     # 1 / total num of words in each topic
    for t in numpy.arange(0,numT):
        input[:,t]=input[:,t]*normalizer

    prob_t_given_d = input.transpose()


    # TODO: add alpha ?

    return prob_t_given_d








def conv_Nwt_to_phi(input):
    """
    convers number of words in topic counts
    to a probability distibution
      p(w|t)
    rows are topics
    columns are word likelyhoods
    """

    numTerms,numT = input.shape

    input = numpy.array( input, dtype=numpy.float )

    prob_w_given_t = numpy.dot(input, numpy.diag(1/numpy.sum(input,0))  )

    # TODO: add beta???

    return prob_w_given_t.transpose()





# FIXME: just copied over the old code needs to be fixed...
def calculate_perplexity(d_w_cnt, prob_w_given_t, prob_t_given_d):
    """ guess what it does """
    # compute the perplexity


    # load the docword
    # assume they are all the same :)
    dwpath = RUN_ROOT+"share/"
    d_w_cnt = get_d_w_cnt(dwpath)


    N=float( sum(d_w_cnt,0)[2] )
    inner_sum=0.0

    for [d,w,cnt] in d_w_cnt:
        prelog = dot(prob_w_given_t[w,:], prob_t_given_d[:,d])
        inner_sum = inner_sum + cnt*log(prelog)

    pplex = exp(-1*inner_sum/N)
    return pplex





