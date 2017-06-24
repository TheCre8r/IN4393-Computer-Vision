import collections
import glob
import operator
import os
import pickle

from scipy.spatial.distance import euclidean
from skimage import draw, feature, io, transform
from skimage.color import gray2rgb, rgb2hsv, rgb2gray, rgba2rgb
from skimage.measure import label
from skimage.morphology import binary_dilation, binary_erosion, binary_closing
from skimage.morphology import disk
from skimage.morphology.misc import remove_small_objects
from skimage.transform import resize
from sklearn import svm

import matplotlib.pyplot as plt
import numpy as np

TRAINING_FOLDER = '../../data/circles_normalized/'
CLASSIFIER_FILE = '../../data/classifiers/svm_circles_normalized.pickle'

HOG_ORIENTATIONS = 9
HOG_CELL_SIZE = (8,8)
HOG_BLOCK_SIZE = (3,3)
HOG_BLOCK_NORM = 'L2-Hys'

# Returns dictonary with all labeled images from the training folder
def load_training_data():
    files = glob.glob(TRAINING_FOLDER + '*.png')
    data = collections.OrderedDict()
    
    for file in files:
        filename = os.path.basename(file)
        label = os.path.splitext(filename)[0]
        
        data[label] = io.imread(file)
    
    return data

# Returns dictonary with feature vector for each training image
def extract_hog_features(training_images):
    training_set = collections.OrderedDict()
    
    for label, image in training_images.iteritems():
        # Fill alpha channel with white and convert image to grayscale
        image = rgba2rgb(image, background=(0,0,0))
        image = rgb2gray(image)
        
        # Extract HOG features
        features = feature.hog(image, HOG_ORIENTATIONS, HOG_CELL_SIZE, HOG_BLOCK_SIZE, HOG_BLOCK_NORM, transform_sqrt=True)
        
        # Show results
        #_, (ax1, ax2) = plt.subplots(1, 2, figsize=(8, 4), sharex=True, sharey=True)
        #ax1.imshow(image, cmap='gray')
        #ax2.imshow(hog_image, cmap='gray')
        #plt.show()
        
        # Add features to training set
        training_set[label] = features
    
    return training_set

# Returns a trained SVM classifier based on training set
def train_classifier(training_set):
    training_samples = training_set.values();
    labels = training_set.keys();
    
    classifier = svm.SVC()
    classifier.fit(training_samples, labels)
    
    return classifier

def detect_circles(image):    
    min_image_size = min(image.shape[0], image.shape[1])
    max_image_size = max(image.shape[0], image.shape[1])
    
    min_radius = max(10, int(min_image_size / 4))
    max_radius = int(max_image_size / 2) 
    
    #print 'Find circles with radius: (%d, %d)' % (min_radius, max_radius)
    
    hough_radii = np.arange(min_radius, max_radius)
    hough_res = transform.hough_circle(image, hough_radii)
    
    min_distance = int(max_image_size / 3)
    threshold = 0.55
    num_peaks = np.inf
    total_num_peaks = 5
    normalize = True
    
    _, cx, cy, radii = transform.hough_circle_peaks(hough_res, hough_radii, min_distance, min_distance, threshold, num_peaks, total_num_peaks, normalize)
    detected_circles = zip(cy, cx, radii)
    
    # cluster circles
    clusters = []
    cluster_distance = 10
    
    for circle in detected_circles:
        distance = None
        
        # Add current circle to an existing cluster if it is nearby this cluster
        for cluster in clusters:
            cluster_mean = np.mean(np.array(cluster)[:,:2], axis=0)
            distance = euclidean(circle[:2], cluster_mean)
            
            if (distance <= cluster_distance):
                cluster.append(circle)
                break
        
        # Create new cluster if circle is not close to an existing cluster
        if distance is None or distance > cluster_distance:
            clusters.append([circle])
        
    # find circles
    circles = []
    
    for cluster in clusters:
        largest_circle = max(cluster, key=operator.itemgetter(2))
        circles.append(largest_circle)
    
    # generate circle image
    circle_image = gray2rgb(image.astype(np.uint8)*255)
    for center_y, center_x, radius in circles:
        #print '=> circle: (%s, %s), radius: %s, intensity: %s' % (center_y, center_x, radius, intensity)
        circy, circx = draw.circle_perimeter(center_y, center_x, radius, shape=image.shape)
        circle_image[circy, circx] = (220, 20, 20)
    
    # return only first circle
    #center_y, center_x, radius = circles[0]
    #circle_mask = np.ones((center_y, center_x), dtype=bool)
    
    #if circles:
    #    circy, circx = draw.circle(circles[0][0], circles[0][1], circles[0][2], shape=image.shape)
    #    circle_mask[circy, circx] = False
    
    # Return results
    return circle_image, circles

def crop_circle(image, circle):
    cropped_image = rgb2gray(image)

    center_y, center_x, radius = circle
    x1 = center_x - radius
    x2 = center_x + radius
    y1 = center_y - radius
    y2 = center_y + radius
    
    circy, circx = draw.circle(center_y, center_x, radius, shape=image.shape)
    mask = np.ones(cropped_image.shape, dtype=bool)
    mask[circy, circx] = False
    
    cropped_image[mask] = 0
    cropped_image = cropped_image[y1:y2, x1:x2]
    
    return cropped_image

def get_hog_features(image):
    image = resize(image, (75,75))
    return feature.hog(image, HOG_ORIENTATIONS, HOG_CELL_SIZE, HOG_BLOCK_SIZE, HOG_BLOCK_NORM, visualise=True, transform_sqrt=True)

def test(image, classifier, debug=True):
    image_size = max(image.shape[0], image.shape[1])
    filter_size = int(image_size / 15)
        
    # Convert to HSV
    image_hsv = rgb2hsv(image)
    
    # Get HSV channels
    H = image_hsv[:,:,0]
    S = image_hsv[:,:,1]
    V = image_hsv[:,:,2]
    
    # Fix H channel
    H[H > 0.8] = 0

    # Red filter constraints
    binary_red = np.logical_and(H <= 0.05, S >= 0.3)
    red_segments = remove_small_objects(binary_red, 64)
    red_segments = binary_closing(red_segments, disk(filter_size))
    red_labels = label(red_segments)

    # Blue filter constraints
    binary_blue = np.logical_and(np.logical_and(H >= 0.55, H <= 0.65), S >= 0.4)
    blue_segments = remove_small_objects(binary_blue, 64)
    blue_segments = binary_closing(blue_segments, disk(filter_size))
    blue_labels = label(blue_segments)
    
    # Detect circles
    red_skeleton = np.logical_xor(binary_dilation(red_segments), binary_erosion(red_segments))
    blue_skeleton = np.logical_xor(binary_dilation(blue_segments), binary_erosion(blue_segments))
    
    red_circles_image, red_circles = detect_circles(red_skeleton)
    blue_circles_image, blue_circles = detect_circles(blue_skeleton)
    
    # Crop circles and extract HOG features
    red_cropped = np.ones(image.shape)
    red_hog_image = np.ones(image.shape)
    red_features = None
    
    blue_cropped = np.ones(image.shape)
    blue_hog_image = np.ones(image.shape)
    blue_features = None
    
    if red_circles:
        red_cropped = crop_circle(image, red_circles[0])
        red_features, red_hog_image = get_hog_features(red_cropped)
        
    if blue_circles:
        blue_cropped = crop_circle(image, blue_circles[0])
        blue_features, blue_hog_image = get_hog_features(blue_cropped)
        
    # Perform classification
    if red_features is not None:
        red_classification = classifier.predict(red_features.reshape(1, -1))
        print 'Result: %s' % red_classification
        
    if blue_features is not None:
        blue_classification = classifier.predict(blue_features.reshape(1, -1))
        print 'Result: %s' % blue_classification
    
    # Display results
    if debug:
        fig, axes = plt.subplots(nrows=3, ncols=5, figsize=(15, 9), sharex=False, sharey=False, subplot_kw={'adjustable':'box-forced'})
        ax = axes.ravel()
        
        ax[0].imshow(image)
        ax[0].set_title('Original image')
        
        ax[1].imshow(H, cmap='gray')
        ax[1].set_title("H channel")
        
        ax[2].imshow(S, cmap='gray')
        ax[2].set_title("S channel")
        
        ax[3].imshow(V, cmap='gray')
        ax[3].set_title("V channel")
        
        ax[5].imshow(binary_red, cmap='gray')
        ax[5].set_title("Binary red")
        
        ax[6].imshow(red_labels, cmap='nipy_spectral')
        ax[6].set_title("Red labels")
        
        ax[7].imshow(red_circles_image)
        ax[7].set_title("Red circles")
        
        ax[8].imshow(red_cropped, cmap='gray')
        ax[8].set_title("Red sign")
        
        ax[9].imshow(red_hog_image, cmap='gray', interpolation='nearest', aspect='auto')
        ax[9].set_title("Red HOG features")
        
        ax[10].imshow(binary_blue, cmap='gray')
        ax[10].set_title("Binary blue")
        
        ax[11].imshow(blue_labels, cmap='nipy_spectral')
        ax[11].set_title("Blue labels")
        
        ax[12].imshow(blue_circles_image)
        ax[12].set_title("Blue circles")
        
        ax[13].imshow(blue_cropped, cmap='gray')
        ax[13].set_title("Blue sign")
        
        ax[14].imshow(blue_hog_image, cmap='gray', interpolation='nearest')
        ax[14].set_title("Blue HOG features")
    
        fig.tight_layout()
        plt.show()

if __name__ == "__main__":
    # Train classifier and save to disk
    #training_set = load_training_data()
    #training_set = extract_hog_features(training_set)
    #classifier = train_classifier(training_set)
    #pickle.dump(classifier, open(CLASSIFIER_FILE, 'wb'), pickle.HIGHEST_PROTOCOL)
    
    # Load classifier
    classifier = pickle.load(open(CLASSIFIER_FILE, 'rb'))
    
    # Perform tests on images
    for filename in glob.glob('../../data/streetview_images_segmented/positive/*.jpg'):
        image = io.imread(filename)
        result = test(image, classifier, debug=True)