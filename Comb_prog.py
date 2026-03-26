# -*- coding: utf-8 -*-
"""
PCB via detection from X-ray CT image slices.

This script:
1. Loads a 3D stack of filtered/aligned PCB X-ray CT slices from a MATLAB file.
2. Splits each slice into overlapping 26x26 image patches.
3. Uses a trained CNN to decide which patches likely contain vias.
4. Runs OpenCV Hough circle detection on selected patches for 3 via-size ranges:
      - small vias
      - medium vias
      - large vias
5. Aggregates all detected circles for each slice.
6. Post-processes detections across many slices to keep only stable / repeated detections.
7. Draws the refined detections back onto saved board images.

Original author:
Created on Fri Jun 29 02:20:23 2018
@author: David
"""

# =========================
# Imports
# =========================
import sys
import timeit
import numpy as np
import scipy.io as sio
from PIL import Image
import cv2

# Keras model is loaded inside Networker(), matching original behavior
# from keras.models import load_model

# =========================
# Timing start
# =========================
start = timeit.default_timer()

# =========================
# Load MATLAB data
# =========================
# This .mat file is expected to contain a 3D stack named 'filtBoardStack'
# with dimensions approximately:
#   [height, width, slice_index]
matz = sio.loadmat(r'C:\Users\David\Desktop\SURF\Data\PCBData\filteredAlignedData.mat')
data_z = matz['filtBoardStack']


# ==========================================================
# Global state
# ==========================================================
# NOTE:
# The original script relies heavily on globals so that helper
# functions can share offsets, detection results, and counters.
# This is preserved here for compatibility, although in a cleaner
# redesign these would be wrapped in a class or passed explicitly.

# Counters for how many times each Hough-based detector finds circles
iu = 0   # large via detector counter
ou = 0   # medium via detector counter
au = 0   # small via detector counter

# Misc globals used while collecting circle data
size = 0
cent_x = 0
cent_y = 0
wye = 0         # y-offset of current patch in the full image
ex = 0          # x-offset of current patch in the full image

# Temporary arrays for circle x, y, r values
actual_0 = 0
actual_1 = 0
actual_2 = 0

# Main detection accumulator for one slice.
# Each row is intended to be [x_center, y_center, radius]
total = [[0 for i in range(3)] for j in range(1)]

# Stores detections for many slices.
# trainee[slice_index] becomes an array of [x, y, r] rows.
trainee = [np.array([0 for i in range(3)]).T for j in range(405)]
for u in range(0, 405):
    trainee[u] = np.reshape(trainee[u], (1, 3))


# ==========================================================
# Helper: detect small vias in a 26x26 patch
# ==========================================================
def slicer(photo):
    """
    Detect small vias (radius approx. 2 to 7 px) in a 26x26 image patch.

    Steps:
    - reshape patch
    - denoise / smooth
    - run Hough circle transform
    - convert local patch coordinates to global board coordinates
    - append detections to the global 'total' list
    """
    global au, cent_x, cent_y, size
    global actual_0, actual_1, actual_2
    global ex, wye, total, progeny

    # Force patch into 26x26
    frame = np.reshape(photo, (26, 26))

    # Convert to uint8 grayscale array
    gray = np.array(Image.fromarray(photo), np.uint8)

    # Copy for optional drawing/debugging
    output = frame.copy()

    # Denoising pipeline
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    gray = cv2.medianBlur(gray, 5)
    gray = cv2.fastNlMeansDenoising(gray)

    # Detect small circles
    circles = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        1,              # inverse ratio of accumulator resolution
        10,             # minimum distance between detected centers
        param1=200,     # upper Canny threshold
        param2=8,       # accumulator threshold
        minRadius=2,
        maxRadius=7
    )

    # If no circles found, do nothing
    if circles is None:
        pass
    else:
        # Round circle results and convert to integer
        circles = np.uint16(np.around(circles))
        cent_x = circles

        # Convert local patch coordinates to global board coordinates
        actual_0 = cent_x[:, :, 0] + ex
        actual_0 = np.transpose(actual_0)

        actual_1 = cent_x[:, :, 1] + wye
        actual_1 = np.transpose(actual_1)

        actual_2 = cent_x[:, :, 2]
        actual_2 = np.transpose(actual_2)

        # Each row becomes [x, y, r]
        progeny = np.hstack((actual_0, actual_1, actual_2))
        total = np.vstack((total, progeny))

        # Keep raw circle arrays for optional later use
        if au == 0:
            cent_y = cent_x
        else:
            cent_y = np.concatenate((cent_y, cent_x), axis=1)

        # Draw circles for debugging if desired
        for i in circles[0, :]:
            cv2.circle(output, (i[0], i[1]), i[2], (0, 0, 255), 1)

        # Original debug save was disabled:
        # cv2.imwrite("Open_CV\\Gray%d.png" % au, gray)
        # cv2.imwrite("Open_CV\\X_Via_%d_%d_%d.png" % (au, wye, ex), output)

        au = au + 1


# ==========================================================
# Helper: detect medium vias in a 26x26 patch
# ==========================================================
def smicer(photo):
    """
    Detect medium vias (radius approx. 8 to 11 px) in a 26x26 patch.
    Same workflow as slicer(), but different Hough radius range.
    """
    global ou, cent_x, cent_y, size
    global actual_0, actual_1, actual_2
    global ex, wye, total, progeny

    frame = np.reshape(photo, (26, 26))
    gray = np.array(Image.fromarray(photo), np.uint8)
    output = frame.copy()

    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    gray = cv2.medianBlur(gray, 5)
    gray = cv2.fastNlMeansDenoising(gray)

    circles = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        1,
        10,
        param1=200,
        param2=8,
        minRadius=8,
        maxRadius=11
    )

    if circles is None:
        pass
    else:
        circles = np.uint16(np.around(circles))
        cent_x = circles

        actual_0 = cent_x[:, :, 0] + ex
        actual_0 = np.transpose(actual_0)

        actual_1 = cent_x[:, :, 1] + wye
        actual_1 = np.transpose(actual_1)

        actual_2 = cent_x[:, :, 2]
        actual_2 = np.transpose(actual_2)

        progeny = np.hstack((actual_0, actual_1, actual_2))
        total = np.vstack((total, progeny))

        if ou == 0:
            cent_y = cent_x
        else:
            cent_y = np.concatenate((cent_y, cent_x), axis=1)

        for i in circles[0, :]:
            cv2.circle(output, (i[0], i[1]), i[2], (0, 255, 0), 1)

        # Original debug save disabled:
        # cv2.imwrite("Open_CV\\Y_Via_%d_%d_%d.png" % (ou, wye, ex), output)

        ou = ou + 1


# ==========================================================
# Helper: detect large vias in a 26x26 patch
# ==========================================================
def sticer(photo):
    """
    Detect large vias (radius approx. 12 to 18 px) in a 26x26 patch.
    Same workflow as slicer(), but tuned for larger circles.
    """
    global iu, cent_x, cent_y, size
    global actual_0, actual_1, actual_2
    global ex, wye, total, progeny

    frame = np.reshape(photo, (26, 26))
    gray = np.array(Image.fromarray(photo), np.uint8)
    output = frame.copy()

    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    gray = cv2.medianBlur(gray, 5)
    gray = cv2.fastNlMeansDenoising(gray)

    circles = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        1,
        5,
        param1=250,
        param2=10,
        minRadius=12,
        maxRadius=18
    )

    if circles is None:
        pass
    else:
        circles = np.uint16(np.around(circles))
        cent_x = circles

        actual_0 = cent_x[:, :, 0] + ex
        actual_0 = np.transpose(actual_0)

        actual_1 = cent_x[:, :, 1] + wye
        actual_1 = np.transpose(actual_1)

        actual_2 = cent_x[:, :, 2]
        actual_2 = np.transpose(actual_2)

        progeny = np.hstack((actual_0, actual_1, actual_2))
        total = np.vstack((total, progeny))

        if iu == 0:
            cent_y = cent_x
        else:
            cent_y = np.concatenate((cent_y, cent_x), axis=1)

        for i in circles[0, :]:
            cv2.circle(output, (i[0], i[1]), i[2], (0, 255, 0), 1)

        # Original debug save disabled:
        # cv2.imwrite("Open_CV\\Z_Via_%d_%d_%d.png" % (iu, wye, ex), output)

        iu = iu + 1


# ==========================================================
# Main per-slice processing function
# ==========================================================
def Networker(fa):
    """
    Process a single CT slice index 'fa'.

    Workflow:
    1. Extract a dense grid of overlapping 26x26 patches from slice fa.
    2. Run a trained CNN on all patches.
    3. For patches above a probability threshold, run small/medium/large
       Hough-circle detection.
    4. Save all detections for this slice into trainee[fa].
    5. Save the full slice image to disk.
    """
    images = np.zeros((20164, 26, 26))
    main_counter = 0

    global ex, wye, total, trainee, df

    # ------------------------------------------------------
    # Slice the board image into overlapping 26x26 patches.
    #
    # 142 x 142 = 20164 patches
    # stride = 13 px, so patches overlap by 50%.
    # ------------------------------------------------------
    for y in range(0, 142):
        for x in range(0, 142):
            pos_x = 13 * x
            prev_x = pos_x + 26

            # Special case for last row to avoid indexing issues
            if y == 141:
                pos_y = 13 * (y - 1)
                prev_y = pos_y + 26
            else:
                pos_y = 13 * y
                prev_y = pos_y + 26

            images[main_counter] = data_z[pos_y:prev_y, pos_x:prev_x, fa]
            main_counter = main_counter + 1

    # ------------------------------------------------------
    # Load the trained CNN classifier
    # ------------------------------------------------------
    from keras.models import load_model
    labeler = load_model('Model_95_63.h5')

    # CNN expects shape: [num_samples, height, width, channels]
    X_tee = np.array(images).reshape(20164, 26, 26, 1)

    # Predict likelihood each patch contains a via-like feature
    y_pred = labeler.predict(X_tee)

    # ------------------------------------------------------
    # For all patches above threshold, run Hough circle detectors
    # ------------------------------------------------------
    i = 0
    for y in range(0, 142):
        for x in range(0, 142):
            i = i + 1

            # If the CNN score is above threshold, treat patch as candidate
            if y_pred[i - 1] > 0.16:
                wye = y * 13   # global y-offset of this patch
                ex = x * 13    # global x-offset of this patch

                images[i - 1] = np.uint8(images[i - 1])

                # Search multiple via radius ranges
                slicer(images[i - 1])   # small vias
                smicer(images[i - 1])   # medium vias
                sticer(images[i - 1])   # large vias

    # Save all detections for this slice
    trainee[fa] = np.vstack((trainee[fa], total))

    # Save the full slice image for later annotation drawing
    temp = data_z[0:1846, 0:1846, fa]
    cv2.imwrite('CNN_Results\\Slice_%d.png' % (fa + 1), temp)


# ==========================================================
# Post-processing / refinement function
# ==========================================================
def marker(num):
    """
    Refine detections for one slice by comparing them to detections
    across many other slices.

    Goal:
    - keep circles that are consistently detected across the stack
    - quantize radii into a few canonical sizes
    - merge nearby duplicate detections
    - draw final circles on the saved slice image
    """
    global trainee

    chosen = trainee[num]

    # Start with a dummy row, matching original script structure
    new_data = [[0 for i in range(3)] for j in range(1)]

    # ------------------------------------------------------
    # Keep detections that are repeated often across slices.
    #
    # A detection is considered "supported" if similar [x,y,r]
    # appears many times across slices 215..254.
    # ------------------------------------------------------
    for h in range(0, len(chosen)):
        grade = 0

        for g in range(215, 255):
            for q in range(0, len(trainee[g])):
                if (
                    abs(chosen[h, 0] - trainee[g][q][0]) < 4 and
                    abs(chosen[h, 1] - trainee[g][q][1]) < 4 and
                    abs(chosen[h, 2] - trainee[g][q][2]) < 4
                ):
                    grade = grade + 1

        # Keep only detections seen often enough
        if grade > 20:
            fi = [[chosen[h, 0], chosen[h, 1], chosen[h, 2]]]
            new_data = np.concatenate([new_data, fi], axis=0)

    # Remove exact duplicate rows
    uniqe = np.unique(new_data, axis=0)

    # ------------------------------------------------------
    # Snap radii into standard buckets
    #
    # This turns slightly different measured radii into
    # canonical sizes representing small / medium / large vias.
    # ------------------------------------------------------
    for j in range(0, len(uniqe)):
        if 0 < uniqe[j, 2] <= 7:
            uniqe[j, 2] = 5
        elif 7 < uniqe[j, 2] <= 11:
            uniqe[j, 2] = 8
        elif 11 < uniqe[j, 2] < 20:
            uniqe[j, 2] = 12

    # ------------------------------------------------------
    # Merge nearby detections.
    #
    # Radius-dependent proximity windows are used:
    # - small:  +/- 9 px
    # - medium: +/- 16 px
    # - large:  +/- 25 px
    #
    # If two detections are close, the one with larger or equal
    # radius dominates, and the smaller one gets overwritten.
    # ------------------------------------------------------
    for q in range(0, len(uniqe)):
        for r in range(0, len(uniqe)):
            # Small via merge window
            if uniqe[q, 2] < 5:
                if (
                    uniqe[q, 0] - 9 < uniqe[r, 0] < uniqe[q, 0] + 9 and
                    uniqe[q, 1] - 9 < uniqe[r, 1] < uniqe[q, 1] + 9
                ):
                    if uniqe[r, 2] <= uniqe[q, 2]:
                        uniqe[r, 0] = uniqe[q, 0]
                        uniqe[r, 1] = uniqe[q, 1]
                        uniqe[r, 2] = uniqe[q, 2]

            # Medium via merge window
            elif 6 < uniqe[q, 2] < 11:
                if (
                    uniqe[q, 0] - 16 < uniqe[r, 0] < uniqe[q, 0] + 16 and
                    uniqe[q, 1] - 16 < uniqe[r, 1] < uniqe[q, 1] + 16
                ):
                    if uniqe[r, 2] <= uniqe[q, 2]:
                        uniqe[r, 0] = uniqe[q, 0]
                        uniqe[r, 1] = uniqe[q, 1]
                        uniqe[r, 2] = uniqe[q, 2]

            # Large via merge window
            elif 10 < uniqe[q, 2] < 20:
                if (
                    uniqe[q, 0] - 25 < uniqe[r, 0] < uniqe[q, 0] + 25 and
                    uniqe[q, 1] - 25 < uniqe[r, 1] < uniqe[q, 1] + 25
                ):
                    if uniqe[r, 2] <= uniqe[q, 2]:
                        uniqe[r, 0] = uniqe[q, 0]
                        uniqe[r, 1] = uniqe[q, 1]
                        uniqe[r, 2] = uniqe[q, 2]

    # Remove duplicates again after merging
    uniqe = np.unique(uniqe, axis=0)

    # Separate x, y, radius columns for drawing
    x = uniqe[:, 0]
    y = uniqe[:, 1]
    r = uniqe[:, 2]

    # Load the saved board slice image
    board = cv2.imread('CNN_Results\\Slice_%d.png' % num)

    # Draw final detections
    for i in range(0, len(uniqe)):
        if 0 < r[i] < 6:
            cv2.circle(board, (x[i], y[i]), r[i], (0, 255, 0), 4)
        elif 5 < r[i] < 10:
            cv2.circle(board, (x[i], y[i]), r[i], (0, 255, 0), 4)
        elif r[i] == 0:
            pass
        else:
            cv2.circle(board, (x[i], y[i]), r[i], (0, 255, 0), 4)

    # Save refined visualization
    cv2.imwrite("Refined\\Board_%d.png" % num, board)


# ==========================================================
# Main execution: process slice range
# ==========================================================
for ta in range(215, 255):
    Networker(ta)

    # Reset global detection state after each slice
    iu = 0
    ou = 0
    au = 0
    size = 0
    cent_x = 0
    cent_y = 0
    wye = 0
    ex = 0
    actual_0 = 0
    actual_1 = 0
    actual_2 = 0
    total = [[0 for i in range(3)] for j in range(1)]
    progeny = 0


# ==========================================================
# Post-process a smaller set of slices for final output
# ==========================================================
for x in range(230, 240):
    marker(x)


# ==========================================================
# Print total runtime
# ==========================================================
stop = timeit.default_timer()
total_time = stop - start

mins, secs = divmod(total_time, 60)
hours, mins = divmod(mins, 60)

sys.stdout.write("Total running time: %d:%d:%d.\n" % (hours, mins, secs))
