import React from 'react';
import { View, Text, TouchableOpacity, ScrollView, Modal, Alert } from 'react-native';

const CartScreen = ({
  cartItems,
  removeFromCart,
  calculateTotal,
  styles,
  bugMode,
  setCurrentScreen,
  showModal,
  setShowModal,
  setCartItems
}) => (
  <View style={styles.screen}>
    <Text style={styles.title} accessibilityLabel="cart-title">Shopping Cart</Text>
    {cartItems.length === 0 ? (
      <Text style={styles.emptyCart} accessibilityLabel="empty-cart-message">
        Your cart is empty
      </Text>
    ) : (
      <View>
        <ScrollView style={styles.cartList}>
          {cartItems.map((item) => (
            <View key={item.id} style={styles.cartItem}>
              <View>
                <Text style={styles.cartItemName}>{item.name}</Text>
                <Text style={styles.cartItemDetails}>
                  ${item.price.toFixed(2)} x {item.qty}
                </Text>
              </View>
              <TouchableOpacity
                style={styles.removeButton}
                onPress={() => removeFromCart(item.id)}
                accessibilityLabel={`remove-item-${item.id}`}
              >
                <Text style={styles.removeButtonText}>✕</Text>
              </TouchableOpacity>
            </View>
          ))}
        </ScrollView>
        <View style={styles.totalRow}>
          <Text style={styles.totalLabel}>Total:</Text>
          <Text style={styles.totalAmount} accessibilityLabel="cart-total">
            ${calculateTotal()}
            {bugMode && <Text style={styles.bugIndicator}> (Overcharged!)</Text>}
          </Text>
        </View>
        <TouchableOpacity
          style={styles.checkoutButton}
          onPress={() => {
            if (bugMode) {
              Alert.alert('Order Placed', 'Thank you!');
              setCartItems([]);
            } else {
              setShowModal(true);
            }
          }}
          accessibilityLabel="checkout-button"
        >
          <Text style={styles.buttonText}>Checkout</Text>
        </TouchableOpacity>
      </View>
    )}
    <TouchableOpacity
      style={styles.backButton}
      onPress={() => setCurrentScreen('home')}
      accessibilityLabel="back-to-home"
    >
      <Text style={styles.backButtonText}>← Back</Text>
    </TouchableOpacity>
    <Modal visible={showModal} transparent animationType="slide">
      <View style={styles.modalOverlay}>
        <View style={styles.modalContent}>
          <Text style={styles.modalTitle}>Confirm Order</Text>
          <Text>Total: ${calculateTotal()}</Text>
          <View style={styles.modalButtons}>
            <TouchableOpacity
              style={styles.modalCancel}
              onPress={() => setShowModal(false)}
              accessibilityLabel="cancel-checkout"
            >
              <Text>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.modalConfirm}
              onPress={() => {
                setShowModal(false);
                setCartItems([]);
                Alert.alert('Success', 'Order placed successfully!');
              }}
              accessibilityLabel="confirm-checkout"
            >
              <Text style={styles.buttonText}>Confirm</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  </View>
);

export default CartScreen;
